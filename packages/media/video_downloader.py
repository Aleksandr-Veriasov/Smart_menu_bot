from __future__ import annotations

import asyncio
import logging
import os
import random
import socket
import time
from typing import Tuple
from urllib.error import HTTPError, URLError

import requests
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

VIDEO_FOLDER = 'videos/'
WIDTH_VIDEO = 720  # Примерный размер, можно изменить
HEIGHT_VIDEO = 1280  # Примерный размер, можно изменить
INACTIVITY_LIMIT_SECONDS = 15 * 60  # 15 минут
DOWNLOADER_BASE_URL = 'http://downloader:8082'

logger = logging.getLogger(__name__)


def _ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        logger.debug(f'📁 Папка для видео создана: {path}')


def _finalize_path(raw_path: str, prefer_ext: str | None = 'mp4') -> str:
    """yt_dlp.prepare_filename(info) даёт путь до постобработки.
    Если мы мерджим в mp4, удобнее вернуть финальный путь .mp4.
    """
    if not prefer_ext:
        return raw_path
    base, _ = os.path.splitext(raw_path)
    return f'{base}.{prefer_ext}'


def _platform_from_url(url: str) -> str:
    u = url.lower()
    if "instagram.com" in u:
        return "instagram"
    if "tiktok.com" in u or "vm.tiktok.com" in u:
        return "tiktok"
    if any(domain in u for domain in ("pinterest.com", "pin.it", "pinterest.co")):
        return "pinterest"
    if "youtube.com" in u or "youtu.be" in u:
        if "/shorts/" in u or "youtube.com/shorts" in u:
            return "youtube_shorts"
        return "youtube"
    return "unknown"


def _random_human_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _yt_dlp_opts(output_path: str) -> dict:
    """
    Настройки с «человечным» поведением:
    - sleep_interval: паузы между запросами/фрагментами
    - retries/fragment_retries: ограниченные ретраи
    - ratelimit: мягкое ограничение скорости (имитируем пользователя)
    - noprogress/quiet: тише в stdout
    """
    return {
        "outtmpl": output_path,
        "format": "bv+ba/best/best",
        "merge_output_format": "mp4",
        "postprocessors": [
            {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
        ],
        "noprogress": True,
        "quiet": True,
        "nocheckcertificate": True,
        "retries": 3,
        "fragment_retries": 3,
        "sleep_interval": 1.0,
        "max_sleep_interval": 3.0,
        "ratelimit": 2_000_000,  # ~2 MB/s
        # Ограничиваем параллелизм фрагментов (по умолчанию = 1 в yt-dlp)
        # "concurrent_fragment_downloads": 1,
        # Чуть более «обычный» User-Agent (yt-dlp сам ставит современный UA)
        # "http_headers": {"User-Agent": "..."},
    }


def _should_retry(err: Exception) -> bool:
    """
    Решаем, стоит ли делать повторную попытку yt-dlp.
    Сетевые/временные ошибки — да. Тяжёлые ошибки (геолокация, удалено) — нет.
    """
    s = str(err).lower()

    # Сетевые/временные
    transient_hints = [
        "timed out",
        "timeout",
        "temporary failure",
        "server error",
        "503 service unavailable",
        "connection reset",
        "network is unreachable",
        "incomplete fragment",
        "http error 5",  # 5xx
    ]
    if any(h in s for h in transient_hints):
        return True

    # OAuth/DRM/гео/удалено — повтор обычно не поможет
    terminal_hints = [
        "copyright",
        "dmca",
        "drm",
        "geo restricted",
        "geo-restricted",
        "unavailable",
        "video has been removed",
        "video unavailable",
        "private video",
        "sign in to confirm your age",
        "age-restricted",
    ]
    if any(h in s for h in terminal_hints):
        return False

    # По умолчанию: 1 повтор попробовать можно
    return True


def _extract_description_from_info(info: dict) -> str:
    """
    Унифицированное извлечение текста: description, title, caption.
    """
    cand = (
        info.get("description")
        or info.get("fulltitle")
        or info.get("title")
        or info.get("caption")
        or ""
    )
    if not cand and "entries" in info and isinstance(info["entries"], list):
        # Плейлисты/мульти-видео
        for it in info["entries"]:
            cand = (
                (it or {}).get("description")
                or (it or {}).get("title")
                or (it or {}).get("caption")
                or ""
            )
            if cand:
                break
    return cand or ""


def _try_download_with_yt_dlp(url: str) -> Tuple[str, str]:
    """
    Одна попытка скачать через yt-dlp. Бросает исключение при неудаче.
    """
    output_path = os.path.join(VIDEO_FOLDER, "%(id)s.%(ext)s")
    ydl_opts = _yt_dlp_opts(output_path)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)  # может бросить
        raw_path = ydl.prepare_filename(info)
        file_path = _finalize_path(raw_path, prefer_ext="mp4")
        desc = _extract_description_from_info(info)
        logger.debug("✅ yt-dlp скачал файл: %s", file_path)
        return file_path, desc


def _download_via_downloader_service(url: str) -> Tuple[str, str]:
    """
    Делегируем скачивание внешнему сервису downloader (Playwright container).
    """
    endpoint = f"{DOWNLOADER_BASE_URL}/download"
    try:
        response = requests.post(endpoint, json={"url": url}, timeout=90)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"downloader service request failed: {exc}"
        ) from exc

    path = payload.get("file_path") or ""
    desc = payload.get("description") or ""
    if not path:
        raise RuntimeError("downloader service returned empty file path.")
    logger.info("✅ Downloader service подготовил файл: %s", path)
    return path, desc


def download_video_and_description(url: str) -> Tuple[str, str]:
    """
    Скачивает видео и возвращает (path, description).
    Сначала пробуем внешний downloader (Instagram/TikTok/Pinterest/YouTube Shorts).
    При неудаче или для других платформ — fallback на yt-dlp.
    """
    _ensure_dir(VIDEO_FOLDER)
    platform = _platform_from_url(url)

    first_exc: Exception | None = None

    # 1) Пытаемся делегировать внешнему сервису (если поддерживаемая платформа)
    downloader_first = {"instagram", "tiktok", "pinterest", "youtube_shorts"}
    if platform in downloader_first:
        try:
            logger.info("🎭 Downloader-сервис обрабатывает ссылку (%s) %s", platform, url)
            return _download_via_downloader_service(url)
        except Exception as downloader_exc:
            first_exc = downloader_exc
            logger.warning(
                "Downloader сервис не справился: %s. Пробуем yt-dlp.",
                downloader_exc,
            )

    # 2) Основной механизм — yt-dlp
    max_attempts = 3
    base_sleep = 1.0  # сек; будет нарастать экспоненциально
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            # Небольшая человеческая задержка перед каждой попыткой
            _random_human_sleep(0.6, 1.8)
            return _try_download_with_yt_dlp(url)
        except (DownloadError, ExtractorError) as e:
            last_exc = e
            logger.warning(
                "yt-dlp ошибка (%d/%d): %s", attempt, max_attempts, e
            )
            # Решаем, стоит ли ретраить yt-dlp
            if attempt < max_attempts and _should_retry(e):
                # экспоненциальная пауза + джиттер
                delay = base_sleep * (2 ** (attempt - 1)) + random.uniform(
                    0.2, 0.8
                )
                delay = min(delay, 6.0)
                logger.debug("Повтор через %.1f сек…", delay)
                time.sleep(delay)
                continue
            else:
                break
        except (
            socket.timeout, URLError, HTTPError, OSError, ConnectionError
        ) as ne:
            last_exc = ne
            logger.warning(
                "Сетевая ошибка (%d/%d): %s", attempt, max_attempts, ne
            )
            if attempt < max_attempts:
                delay = base_sleep * (2 ** (attempt - 1)) + random.uniform(
                    0.1, 0.6
                )
                delay = min(delay, 5.0)
                time.sleep(delay)
                continue
            break
        except Exception as e:
            # Прочие ошибки — завершаем без агрессивных ретраев
            last_exc = e
            logger.error("Неожиданная ошибка: %s", e, exc_info=True)
            break

    if first_exc:
        logger.error("❌ Downloader сервис не справился: %s", first_exc, exc_info=True)
    logger.error("❌ Не удалось скачать видео: %s", last_exc)
    return "", ""


async def async_download_video_and_description(url: str) -> Tuple[str, str]:
    """
    Асинхронная обёртка поверх блокирующей загрузки.
    """
    return await asyncio.to_thread(download_video_and_description, url)


async def cleanup_old_videos() -> None:
    """Фоновая задача, удаляющая старые видеофайлы без активности."""
    while True:
        logger.info('Фоновая задача начала работать')
        now = time.time()
        if os.path.exists(VIDEO_FOLDER):
            for filename in os.listdir(VIDEO_FOLDER):
                file_path = os.path.join(VIDEO_FOLDER, filename)
                try:
                    if os.path.isfile(file_path):
                        last_access = os.path.getatime(file_path)
                        if now - last_access > INACTIVITY_LIMIT_SECONDS:
                            os.remove(file_path)
                            logger.debug(
                                f'Удалён неиспользуемый файл: {file_path}'
                            )
                except Exception as e:
                    logger.error(
                        f'Ошибка при удалении файла: {file_path} — {e}'
                    )
        await asyncio.sleep(INACTIVITY_LIMIT_SECONDS)
