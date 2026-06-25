import asyncio
import logging
import os

import requests

VIDEO_FOLDER = "videos/"
DOWNLOADER_BASE_URL = os.getenv("DOWNLOADER_BASE_URL", "http://downloader:8082").rstrip("/")

logger = logging.getLogger(__name__)


def _ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        logger.debug(f"📁 Папка для видео создана: {path}")


def download_video_and_description(url: str) -> tuple[str, str]:
    """
    Делегирует скачивание в сервис downloader.
    """
    _ensure_dir(VIDEO_FOLDER)

    endpoint = f"{DOWNLOADER_BASE_URL}/download"
    try:
        response = requests.post(endpoint, json={"url": url}, timeout=120)
        response.raise_for_status()
        payload = response.json()
        file_path = payload.get("file_path") or ""
        description = payload.get("description") or ""
        if not file_path:
            logger.error("Сервис downloader вернул пустой путь к файлу.")
            return "", ""
        logger.debug(f"✅ Сервис downloader вернул файл: {file_path}")
        return file_path, description
    except Exception as exc:
        logger.error(f"Сервис downloader не ответил: {exc}", exc_info=True)
        return "", ""


async def async_download_video_and_description(url: str) -> tuple[str, str]:
    """
    Асинхронная обёртка поверх HTTP-запроса.
    """
    return await asyncio.to_thread(download_video_and_description, url)
