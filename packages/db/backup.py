from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from packages.common_settings.settings import DatabaseSettings, settings

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """Ошибка процесса бэкапа PostgreSQL."""


class PostgresDumpService:
    """Сервис создания дампа PostgreSQL и пост-обработки (Dropbox + ротация)."""

    def __init__(self, cfg: DatabaseSettings) -> None:
        self.cfg = cfg
        self.dump_path = self._resolve_dump_file_path()

    def _resolve_dump_file_path(self) -> Path:
        """Строит путь к новому файлу дампа и гарантирует существование директории."""
        dump_dir = Path(self.cfg.dump_dir).expanduser()
        dump_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_name = f"{self.cfg.dump_filename_prefix}_{self.cfg.database_name}_{stamp}.dump"
        return dump_dir / file_name

    def _extract_dump_timestamp(self, file_name: str) -> datetime | None:
        """Извлекает UTC timestamp из имени дампа, если формат совпадает."""
        pattern = (
            rf"^{re.escape(self.cfg.dump_filename_prefix)}_"
            rf"{re.escape(self.cfg.database_name)}_"
            r"(\d{8}T\d{6}Z)\.dump$"
        )
        match = re.match(pattern, file_name)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _cleanup_local_retention(self) -> int:
        """Удаляет локальные дампы старше retention-периода и возвращает число удалённых."""
        dump_dir = Path(self.cfg.dump_dir).expanduser()
        if not dump_dir.exists():
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.dump_retention_days)
        removed = 0
        for file_path in dump_dir.glob(f"{self.cfg.dump_filename_prefix}_{self.cfg.database_name}_*.dump"):
            ts = self._extract_dump_timestamp(file_path.name)
            if ts is not None and ts < cutoff and file_path.is_file():
                file_path.unlink(missing_ok=True)
                removed += 1
        return removed

    def _build_pg_dump_cmd(self) -> list[str]:
        """Собирает argv для запуска pg_dump."""
        return [
            "pg_dump",
            "--host",
            self.cfg.host,
            "--port",
            str(self.cfg.port),
            "--username",
            self.cfg.username,
            "--format",
            "custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(self.dump_path),
            self.cfg.database_name,
        ]

    def _build_pg_env(self) -> dict[str, str]:
        """Готовит окружение для pg_dump (пароль и SSL-параметры libpq)."""
        env = os.environ.copy()
        env["PGPASSWORD"] = self.cfg.password.get_secret_value()

        effective_ssl = self.cfg._effective_ssl_mode(use_async=False)
        if effective_ssl is not None:
            env["PGSSLMODE"] = effective_ssl.value
        if self.cfg.ssl_root_cert_file:
            env["PGSSLROOTCERT"] = self.cfg.ssl_root_cert_file

        return env

    async def create_dump(self) -> Path:
        if shutil.which("pg_dump") is None:
            raise BackupError("pg_dump not found in PATH")

        cmd = self._build_pg_dump_cmd()
        env = self._build_pg_env()

        logger.info(f"Запускаем pg_dump в {self.dump_path}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.cfg.dump_pg_timeout_sec)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            if self.dump_path.exists():
                self.dump_path.unlink(missing_ok=True)
            raise BackupError(f"pg_dump timed out after {self.cfg.dump_pg_timeout_sec}s") from exc

        if process.returncode != 0:
            if self.dump_path.exists():
                self.dump_path.unlink(missing_ok=True)
            error = (stderr or stdout).decode("utf-8", errors="ignore").strip()
            raise BackupError(f"pg_dump failed with code {process.returncode}: {error}")

        dropbox_path = await asyncio.to_thread(DropboxDumpClient(self.cfg, self.dump_path).upload_dump)
        logger.info(f"Дамп БД загружен в Dropbox: {dropbox_path}")

        try:
            removed_local = self._cleanup_local_retention()
            if removed_local > 0:
                logger.info(
                    f"Локальная ротация дампов: удалено {removed_local} файлов "
                    f"(older than {self.cfg.dump_retention_days} days)"
                )
        except Exception:
            logger.exception("Ошибка локальной ротации дампов")

        try:
            removed_dropbox = await asyncio.to_thread(DropboxDumpClient(self.cfg).cleanup_retention)
            if removed_dropbox > 0:
                logger.info(
                    f"Dropbox ротация дампов: удалено {removed_dropbox} файлов "
                    f"(older than {self.cfg.dump_retention_days} days)"
                )
        except Exception:
            logger.exception("Ошибка ротации дампов в Dropbox")

        logger.info(f"Дамп БД успешно создан: {self.dump_path}")
        return self.dump_path


class DropboxDumpClient:
    """Клиент Dropbox для загрузки и ротации дампов БД."""

    def __init__(self, cfg: DatabaseSettings, dump_path: Path | None = None) -> None:
        self.cfg = cfg
        self.dropbox_cfg = cfg.dump_dropbox
        self.dump_path = dump_path
        self.file_name = dump_path.name if dump_path is not None else ""
        self.timeout = self.dropbox_cfg.timeout_sec
        self._access_token = ""

    @staticmethod
    def _normalize_root_path(root_path: str) -> str:
        """Нормализует корневой путь Dropbox к виду '/path' или '/'."""
        root = root_path.strip()
        if not root:
            root = "/"
        if not root.startswith("/"):
            root = f"/{root}"
        root = "/" if root == "/" else root.rstrip("/")
        return root

    def _build_destination_path(self) -> str:
        root = self._normalize_root_path(self.dropbox_cfg.root_path)
        return f"{root}/{self.file_name}" if root else f"/{self.file_name}"

    def _extract_dump_timestamp(self, file_name: str) -> datetime | None:
        pattern = (
            rf"^{re.escape(self.cfg.dump_filename_prefix)}_"
            rf"{re.escape(self.cfg.database_name)}_"
            r"(\d{8}T\d{6}Z)\.dump$"
        )
        match = re.match(pattern, file_name)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _headers(self, api_arg: dict[str, Any]) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps(api_arg, separators=(",", ":")),
        }

    def _json_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_for_error(resp: requests.Response) -> None:
        if resp.ok:
            return
        body = resp.text[:500]
        raise BackupError(f"Dropbox upload failed ({resp.status_code}): {body}")

    @staticmethod
    def _is_auth_error(resp: requests.Response) -> bool:
        return resp.status_code == 401

    def _refresh_access_token(self) -> str:
        refresh_token = self.dropbox_cfg.refresh_token.get_secret_value().strip()
        app_key = self.dropbox_cfg.app_key.get_secret_value().strip()
        app_secret = self.dropbox_cfg.app_secret.get_secret_value().strip()

        if not (refresh_token and app_key and app_secret):
            raise BackupError(
                "Dropbox access token expired and refresh is not configured. "
                "Set DB_DUMP_DROPBOX_REFRESH_TOKEN, DB_DUMP_DROPBOX_APP_KEY, DB_DUMP_DROPBOX_APP_SECRET."
            )

        resp = requests.post(
            f"{self.dropbox_cfg.oauth_api_base}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": app_key,
                "client_secret": app_secret,
            },
            timeout=self.timeout,
        )
        if not resp.ok:
            body = resp.text[:500]
            raise BackupError(f"Dropbox token refresh failed ({resp.status_code}): {body}")

        token = str(resp.json().get("access_token", "")).strip()
        if not token:
            raise BackupError("Dropbox token refresh returned empty access_token")
        logger.info("Токен доступа Dropbox успешно обновлён")
        return token

    def _post_with_refresh(
        self,
        *,
        url: str,
        build_headers: Callable[[], dict[str, str]],
        data: bytes | str | None = None,
    ) -> requests.Response:
        if not self._access_token:
            self._access_token = self._refresh_access_token()

        headers = build_headers()
        resp = requests.post(url, headers=headers, data=data, timeout=self.timeout)
        if not self._is_auth_error(resp):
            return resp

        self._access_token = self._refresh_access_token()
        headers = build_headers()
        return requests.post(url, headers=headers, data=data, timeout=self.timeout)

    def _content_post(
        self,
        endpoint: str,
        api_arg: dict[str, Any],
        data: bytes | str | None = None,
    ) -> requests.Response:
        return self._post_with_refresh(
            url=f"{self.dropbox_cfg.content_api_base}/{endpoint}",
            build_headers=lambda: self._headers(api_arg),
            data=data,
        )

    def _rpc_post(self, endpoint: str, payload: dict[str, Any]) -> requests.Response:
        return self._post_with_refresh(
            url=f"{self.dropbox_cfg.api_base}/{endpoint}",
            build_headers=self._json_headers,
            data=json.dumps(payload),
        )

    def upload_dump(self) -> str:
        if self.dump_path is None:
            raise BackupError("DropboxDumpClient requires dump_path for upload")

        destination_path = self._build_destination_path()
        size = self.dump_path.stat().st_size

        if size <= self.dropbox_cfg.chunk_size_bytes:
            with self.dump_path.open("rb") as fh:
                data = fh.read()
            resp = self._content_post(
                "upload",
                {
                    "path": destination_path,
                    "mode": "overwrite",
                    "autorename": False,
                    "mute": True,
                    "strict_conflict": False,
                },
                data=data,
            )
            self._raise_for_error(resp)
            return destination_path

        with self.dump_path.open("rb") as fh:
            first_chunk = fh.read(self.dropbox_cfg.chunk_size_bytes)
            start_resp = self._content_post(
                "upload_session/start",
                {"close": False},
                data=first_chunk,
            )
            self._raise_for_error(start_resp)
            session_id = start_resp.json().get("session_id")
            if not session_id:
                raise BackupError("Dropbox upload_session/start returned empty session_id")

            offset = len(first_chunk)
            while (size - offset) > self.dropbox_cfg.chunk_size_bytes:
                chunk = fh.read(self.dropbox_cfg.chunk_size_bytes)
                append_resp = self._content_post(
                    "upload_session/append_v2",
                    {"cursor": {"session_id": session_id, "offset": offset}, "close": False},
                    data=chunk,
                )
                self._raise_for_error(append_resp)
                offset += len(chunk)

            tail = fh.read(self.dropbox_cfg.chunk_size_bytes)
            finish_resp = self._content_post(
                "upload_session/finish",
                {
                    "cursor": {"session_id": session_id, "offset": offset},
                    "commit": {
                        "path": destination_path,
                        "mode": "overwrite",
                        "autorename": False,
                        "mute": True,
                        "strict_conflict": False,
                    },
                },
                data=tail,
            )
            self._raise_for_error(finish_resp)
        return destination_path

    def _list_folder(self, *, path: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        if cursor is None:
            payload: dict[str, Any] = {"path": path or "", "recursive": False, "include_non_downloadable_files": False}
            resp = self._rpc_post("list_folder", payload)
            self._raise_for_error(resp)
            return resp.json()

        payload = {"cursor": cursor}
        resp = self._rpc_post("list_folder/continue", payload)
        self._raise_for_error(resp)
        return resp.json()

    def cleanup_retention(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.dump_retention_days)
        root = self._normalize_root_path(self.dropbox_cfg.root_path)
        list_path = "" if root == "/" else root
        removed = 0

        cursor: str | None = None
        has_more = True
        while has_more:
            data = self._list_folder(path=list_path, cursor=cursor)
            for entry in data.get("entries", []):
                if entry.get(".tag") != "file":
                    continue
                name = entry.get("name", "")
                ts = self._extract_dump_timestamp(name)
                if ts is None or ts >= cutoff:
                    continue
                file_path = entry.get("path_lower") or entry.get("path_display")
                if not file_path:
                    continue

                delete_resp = self._rpc_post("delete_v2", {"path": file_path})
                self._raise_for_error(delete_resp)
                removed += 1

            has_more = bool(data.get("has_more"))
            cursor = data.get("cursor")

        return removed


# Public API
def _next_run_at(hour_utc: int, minute_utc: int) -> datetime:
    """Возвращает ближайший момент запуска по UTC для заданного часа и минуты."""
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=hour_utc, minute=minute_utc, second=0, microsecond=0)
    if next_run <= now:
        next_run = next_run + timedelta(days=1)
    return next_run


async def run_daily_dump_scheduler() -> None:
    """Фоновый планировщик: ежедневно создаёт и отправляет дамп в заданное UTC-время."""
    cfg = settings.db

    logger.info(
        f"Планировщик дампов запущен: ежедневно в "
        f"{cfg.dump_schedule_hour_utc:02d}:{cfg.dump_schedule_minute_utc:02d} UTC"
    )

    while True:
        next_run = _next_run_at(cfg.dump_schedule_hour_utc, cfg.dump_schedule_minute_utc)
        delay = (next_run - datetime.now(timezone.utc)).total_seconds()
        logger.info(f"Следующий дамп БД запланирован на {next_run.isoformat()}")

        await asyncio.sleep(max(delay, 0))

        try:
            await PostgresDumpService(cfg).create_dump()
        except Exception:
            logger.exception("Ошибка планового дампа БД, продолжаем планировщик")
