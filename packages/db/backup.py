from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from packages.common_settings.settings import DatabaseSettings, settings

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """Ошибка процесса бэкапа PostgreSQL."""


def _next_run_at(hour_utc: int, minute_utc: int) -> datetime:
    """Возвращает ближайший момент запуска по UTC для заданного часа и минуты."""
    now = datetime.now(timezone.utc)
    next_run = now.replace(hour=hour_utc, minute=minute_utc, second=0, microsecond=0)
    if next_run <= now:
        next_run = next_run + timedelta(days=1)
    return next_run


def _resolve_dump_file_path(db_settings: DatabaseSettings) -> Path:
    """Строит путь к новому файлу дампа и гарантирует существование директории."""
    dump_dir = Path(db_settings.dump_dir).expanduser()
    dump_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    file_name = f"{db_settings.dump_filename_prefix}_{db_settings.database_name}_{stamp}.dump"
    return dump_dir / file_name


def _extract_dump_timestamp(file_name: str, db_settings: DatabaseSettings) -> datetime | None:
    """Извлекает UTC timestamp из имени дампа, если формат совпадает."""
    pattern = (
        rf"^{re.escape(db_settings.dump_filename_prefix)}_"
        rf"{re.escape(db_settings.database_name)}_"
        r"(\d{8}T\d{6}Z)\.dump$"
    )
    match = re.match(pattern, file_name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _cleanup_local_retention(db_settings: DatabaseSettings) -> int:
    """Удаляет локальные дампы старше retention-периода и возвращает число удалённых."""
    dump_dir = Path(db_settings.dump_dir).expanduser()
    if not dump_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=db_settings.dump_retention_days)
    removed = 0
    for file_path in dump_dir.glob(f"{db_settings.dump_filename_prefix}_{db_settings.database_name}_*.dump"):
        ts = _extract_dump_timestamp(file_path.name, db_settings)
        if ts is not None and ts < cutoff and file_path.is_file():
            file_path.unlink(missing_ok=True)
            removed += 1
    return removed


def _build_pg_dump_cmd(db_settings: DatabaseSettings, dump_path: Path) -> list[str]:
    """Собирает argv для запуска pg_dump."""
    return [
        "pg_dump",
        "--host",
        db_settings.host,
        "--port",
        str(db_settings.port),
        "--username",
        db_settings.username,
        "--format",
        "custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(dump_path),
        db_settings.database_name,
    ]


def _build_pg_env(db_settings: DatabaseSettings) -> dict[str, str]:
    """Готовит окружение для pg_dump (пароль и SSL-параметры libpq)."""
    env = os.environ.copy()
    env["PGPASSWORD"] = db_settings.password.get_secret_value()

    effective_ssl = db_settings._effective_ssl_mode(use_async=False)
    if effective_ssl is not None:
        env["PGSSLMODE"] = effective_ssl.value
    if db_settings.ssl_root_cert_file:
        env["PGSSLROOTCERT"] = db_settings.ssl_root_cert_file

    return env


async def create_postgres_dump(db_settings: DatabaseSettings | None = None) -> Path:
    """Создаёт дамп БД, загружает его в Dropbox и запускает ротацию."""
    cfg = db_settings or settings.db

    if shutil.which("pg_dump") is None:
        raise BackupError("pg_dump not found in PATH")

    dump_path = _resolve_dump_file_path(cfg)
    cmd = _build_pg_dump_cmd(cfg, dump_path)
    env = _build_pg_env(cfg)

    logger.info(f"Запускаем pg_dump в {dump_path}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=cfg.dump_pg_timeout_sec)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        if dump_path.exists():
            dump_path.unlink(missing_ok=True)
        raise BackupError(f"pg_dump timed out after {cfg.dump_pg_timeout_sec}s") from exc

    if process.returncode != 0:
        if dump_path.exists():
            dump_path.unlink(missing_ok=True)
        error = (stderr or stdout).decode("utf-8", errors="ignore").strip()
        raise BackupError(f"pg_dump failed with code {process.returncode}: {error}")

    dropbox_path = await upload_dump_to_dropbox(dump_path, cfg)
    logger.info(f"Дамп БД загружен в Dropbox: {dropbox_path}")

    try:
        removed_local = _cleanup_local_retention(cfg)
        if removed_local > 0:
            logger.info(
                f"Локальная ротация дампов: удалено {removed_local} файлов "
                f"(older than {cfg.dump_retention_days} days)"
            )
    except Exception:
        logger.exception("Ошибка локальной ротации дампов")

    try:
        removed_dropbox = await cleanup_dropbox_retention(cfg)
        if removed_dropbox > 0:
            logger.info(
                f"Dropbox ротация дампов: удалено {removed_dropbox} файлов "
                f"(older than {cfg.dump_retention_days} days)"
            )
    except Exception:
        logger.exception("Ошибка ротации дампов в Dropbox")

    logger.info(f"Дамп БД успешно создан: {dump_path}")
    return dump_path


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
            await create_postgres_dump(cfg)
        except Exception:
            logger.exception("Ошибка планового дампа БД, продолжаем планировщик")


def _normalize_dropbox_root_path(root_path: str) -> str:
    """Нормализует корневой путь Dropbox к виду '/path' или '/'."""
    root = root_path.strip()
    if not root:
        root = "/"
    if not root.startswith("/"):
        root = f"/{root}"
    root = "/" if root == "/" else root.rstrip("/")
    return root


def _build_dropbox_destination_path(cfg: DatabaseSettings, file_name: str) -> str:
    """Формирует полный путь файла дампа в Dropbox."""
    root = _normalize_dropbox_root_path(cfg.dump_dropbox_root_path)
    return f"{root}/{file_name}" if root else f"/{file_name}"


def _dropbox_headers(token: str, api_arg: dict[str, Any]) -> dict[str, str]:
    """Возвращает заголовки для Dropbox Content API."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps(api_arg, separators=(",", ":")),
    }


def _dropbox_json_headers(token: str) -> dict[str, str]:
    """Возвращает JSON-заголовки для Dropbox RPC API."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _dropbox_raise_for_error(resp: requests.Response) -> None:
    """Поднимает BackupError, если ответ Dropbox неуспешен."""
    if resp.ok:
        return
    body = resp.text[:500]
    raise BackupError(f"Dropbox upload failed ({resp.status_code}): {body}")


def _upload_dump_to_dropbox_sync(dump_path: Path, cfg: DatabaseSettings) -> str:
    """Синхронно загружает дамп в Dropbox (обычная загрузка или upload session)."""
    token = cfg.dump_dropbox_access_token.get_secret_value()

    timeout = cfg.dump_dropbox_timeout_sec
    destination_path = _build_dropbox_destination_path(cfg, dump_path.name)
    size = dump_path.stat().st_size

    if size <= cfg.dump_dropbox_chunk_size_bytes:
        with dump_path.open("rb") as fh:
            data = fh.read()
        resp = requests.post(
            f"{cfg.dump_dropbox_content_api_base}/upload",
            headers=_dropbox_headers(
                token,
                {
                    "path": destination_path,
                    "mode": "overwrite",
                    "autorename": False,
                    "mute": True,
                    "strict_conflict": False,
                },
            ),
            data=data,
            timeout=timeout,
        )
        _dropbox_raise_for_error(resp)
        return destination_path

    with dump_path.open("rb") as fh:
        first_chunk = fh.read(cfg.dump_dropbox_chunk_size_bytes)
        start_resp = requests.post(
            f"{cfg.dump_dropbox_content_api_base}/upload_session/start",
            headers=_dropbox_headers(token, {"close": False}),
            data=first_chunk,
            timeout=timeout,
        )
        _dropbox_raise_for_error(start_resp)
        session_id = start_resp.json().get("session_id")
        if not session_id:
            raise BackupError("Dropbox upload_session/start returned empty session_id")

        offset = len(first_chunk)
        while (size - offset) > cfg.dump_dropbox_chunk_size_bytes:
            chunk = fh.read(cfg.dump_dropbox_chunk_size_bytes)
            append_resp = requests.post(
                f"{cfg.dump_dropbox_content_api_base}/upload_session/append_v2",
                headers=_dropbox_headers(
                    token, {"cursor": {"session_id": session_id, "offset": offset}, "close": False}
                ),
                data=chunk,
                timeout=timeout,
            )
            _dropbox_raise_for_error(append_resp)
            offset += len(chunk)

        tail = fh.read(cfg.dump_dropbox_chunk_size_bytes)
        finish_resp = requests.post(
            f"{cfg.dump_dropbox_content_api_base}/upload_session/finish",
            headers=_dropbox_headers(
                token,
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
            ),
            data=tail,
            timeout=timeout,
        )
        _dropbox_raise_for_error(finish_resp)
    return destination_path


async def upload_dump_to_dropbox(dump_path: Path, cfg: DatabaseSettings) -> str:
    """Асинхронная обёртка над синхронной загрузкой дампа в Dropbox."""
    logger.info(f"Загружаем дамп в Dropbox: file={dump_path.name}")
    return await asyncio.to_thread(_upload_dump_to_dropbox_sync, dump_path, cfg)


def _cleanup_dropbox_retention_sync(cfg: DatabaseSettings) -> int:
    """Удаляет в Dropbox дампы старше retention-периода и возвращает число удалённых."""
    token = cfg.dump_dropbox_access_token.get_secret_value()
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.dump_retention_days)
    root = _normalize_dropbox_root_path(cfg.dump_dropbox_root_path)
    list_path = "" if root == "/" else root
    timeout = cfg.dump_dropbox_timeout_sec
    removed = 0

    def _list_folder(path: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        if cursor is None:
            payload: dict[str, Any] = {"path": path or "", "recursive": False, "include_non_downloadable_files": False}
            resp = requests.post(
                f"{cfg.dump_dropbox_api_base}/list_folder",
                headers=_dropbox_json_headers(token),
                data=json.dumps(payload),
                timeout=timeout,
            )
            _dropbox_raise_for_error(resp)
            return resp.json()
        payload = {"cursor": cursor}
        resp = requests.post(
            f"{cfg.dump_dropbox_api_base}/list_folder/continue",
            headers=_dropbox_json_headers(token),
            data=json.dumps(payload),
            timeout=timeout,
        )
        _dropbox_raise_for_error(resp)
        return resp.json()

    cursor: str | None = None
    has_more = True
    while has_more:
        data = _list_folder(path=list_path, cursor=cursor)
        for entry in data.get("entries", []):
            if entry.get(".tag") != "file":
                continue
            name = entry.get("name", "")
            ts = _extract_dump_timestamp(name, cfg)
            if ts is None or ts >= cutoff:
                continue
            file_path = entry.get("path_lower") or entry.get("path_display")
            if not file_path:
                continue

            delete_resp = requests.post(
                f"{cfg.dump_dropbox_api_base}/delete_v2",
                headers=_dropbox_json_headers(token),
                data=json.dumps({"path": file_path}),
                timeout=timeout,
            )
            _dropbox_raise_for_error(delete_resp)
            removed += 1

        has_more = bool(data.get("has_more"))
        cursor = data.get("cursor")

    return removed


async def cleanup_dropbox_retention(cfg: DatabaseSettings) -> int:
    """Асинхронная обёртка для Dropbox-ротации дампов."""
    return await asyncio.to_thread(_cleanup_dropbox_retention_sync, cfg)
