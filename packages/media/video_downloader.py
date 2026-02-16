import asyncio
import logging
import os
import time

import requests

VIDEO_FOLDER = "videos/"
INACTIVITY_LIMIT_SECONDS = 15 * 60  # 15 минут
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


async def cleanup_old_videos() -> None:
    """Фоновая задача, удаляющая старые видеофайлы без активности."""
    while True:
        logger.info("Фоновая задача начала работать")
        now = time.time()
        if os.path.exists(VIDEO_FOLDER):
            for filename in os.listdir(VIDEO_FOLDER):
                if filename == ".gitkeep":
                    continue
                file_path = os.path.join(VIDEO_FOLDER, filename)
                try:
                    if os.path.isfile(file_path):
                        last_access = os.path.getatime(file_path)
                        if now - last_access > INACTIVITY_LIMIT_SECONDS:
                            os.remove(file_path)
                            logger.debug(f"Удалён неиспользуемый файл: {file_path}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении файла: {file_path} — {e}")
        await asyncio.sleep(INACTIVITY_LIMIT_SECONDS)
