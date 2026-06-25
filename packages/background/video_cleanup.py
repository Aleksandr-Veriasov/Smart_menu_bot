import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

VIDEO_FOLDER = "videos/"
INACTIVITY_LIMIT_SECONDS = 15 * 60  # 15 минут


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
                            logger.debug("Удалён неиспользуемый файл: %s", file_path)
                except Exception as e:
                    logger.error("Ошибка при удалении файла: %s — %s", file_path, e)
        await asyncio.sleep(INACTIVITY_LIMIT_SECONDS)
