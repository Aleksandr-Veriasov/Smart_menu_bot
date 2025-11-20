from __future__ import annotations

import logging
import os
import random
import socket
import time
from pathlib import Path
from typing import Tuple
from urllib.error import HTTPError, URLError

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from downloader.playwright_service import (
    _platform_from_url,
    download_with_playwright,
)

VIDEO_FOLDER = Path("/app/videos")
VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def _finalize_path(raw_path: str, prefer_ext: str | None = "mp4") -> str:
    if not prefer_ext:
        return raw_path
    base, _ = os.path.splitext(raw_path)
    return f"{base}.{prefer_ext}"


def _yt_dlp_opts(output_path: str) -> dict:
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
        "ratelimit": 2_000_000,
        "cachedir": "/app/.cache/yt-dlp",
    }


def _should_retry(err: Exception) -> bool:
    s = str(err).lower()
    transient = [
        "timed out",
        "timeout",
        "temporary failure",
        "server error",
        "503 service unavailable",
        "connection reset",
        "network is unreachable",
        "incomplete fragment",
        "http error 5",
    ]
    if any(h in s for h in transient):
        return True

    terminal = [
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
    if any(h in s for h in terminal):
        return False
    return True


def _extract_description_from_info(info: dict) -> str:
    cand = (
        info.get("description")
        or info.get("fulltitle")
        or info.get("title")
        or info.get("caption")
        or ""
    )
    if not cand and "entries" in info and isinstance(info["entries"], list):
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
    output_path = str(VIDEO_FOLDER / "%(id)s.%(ext)s")
    ydl_opts = _yt_dlp_opts(output_path)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        raw_path = ydl.prepare_filename(info)
        file_path = _finalize_path(raw_path, prefer_ext="mp4")
        desc = _extract_description_from_info(info)
        logger.debug(f"✅ yt-dlp скачал файл: {file_path}")
        return file_path, desc


def download_video(url: str) -> Tuple[str, str]:
    platform = _platform_from_url(url)
    logger.info(f"🎬 Запрос на скачивание {url} ({platform})")
    first_exc: Exception | None = None

    playwright_platforms = {"instagram", "tiktok"}
    if platform in playwright_platforms:
        try:
            return download_with_playwright(url)
        except Exception as exc:
            first_exc = exc
            logger.warning(f"⚠️ Playwright не справился: {exc}")

    max_attempts = 3
    base_sleep = 1.0
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            delay = random.uniform(0.6, 1.8)
            time.sleep(delay)
            return _try_download_with_yt_dlp(url)
        except (DownloadError, ExtractorError) as e:
            last_exc = e
            logger.warning(f"⚠️ yt-dlp ошибка ({attempt}/{max_attempts}): {e}")
            if attempt < max_attempts and _should_retry(e):
                sleep_for = base_sleep * (2 ** (attempt - 1)) + random.uniform(
                    0.2, 0.8
                )
                sleep_for = min(sleep_for, 6.0)
                logger.debug(f"🔁 Повтор yt-dlp через {sleep_for:.1f} сек")
                time.sleep(sleep_for)
                continue
            break
        except (
            socket.timeout,
            URLError,
            HTTPError,
            OSError,
            ConnectionError,
        ) as network_err:
            last_exc = network_err
            logger.warning(
                f"🌐 Сетевая ошибка ({attempt}/{max_attempts}): {network_err}"
            )
            if attempt < max_attempts:
                sleep_for = base_sleep * (2 ** (attempt - 1)) + random.uniform(
                    0.1, 0.6
                )
                sleep_for = min(sleep_for, 5.0)
                logger.debug(
                    f"🔁 Повтор после сетевой ошибки через {sleep_for:.1f} сек"
                )
                time.sleep(sleep_for)
                continue
            break
        except Exception as e:  # noqa: BLE001
            last_exc = e
            logger.error(f"Неожиданная ошибка yt-dlp: {e}", exc_info=True)
            break

    if first_exc:
        logger.error(f"Playwright упал ранее: {first_exc}", exc_info=True)
    logger.error(f"yt-dlp тоже не справился: {last_exc}", exc_info=True)
    raise RuntimeError("Не удалось скачать видео через downloader")
