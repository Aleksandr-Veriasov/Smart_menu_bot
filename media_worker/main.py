"""media_worker — точка входа.

Цикл:
  1. claim job из pipeline_jobs (FOR UPDATE SKIP LOCKED)
  2. pipeline.run(job) — скачать / транскрибировать / сохранить / уведомить
  3. ack (успех) или nack (ошибка, backoff/failed)

Фоновая задача: whisper_model.unload_loop() — выгружает модель после TTL простоя.
"""

import asyncio
import logging

from media_worker.notifications.notifier import MediaWorkerNotifier
from media_worker.transcription import whisper_model
from media_worker.worker.poller import poll_loop
from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.logging_config import setup_logging
from packages.redis.redis_conn import get_redis

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    logger.info("media_worker starting…")

    db = Database(settings.db.sqlalchemy_url(use_async=True), null_pool=True)
    logger.info("✅ Database connected")

    redis = await get_redis()
    logger.info("✅ Redis connected")

    state = AppState(db=db, redis=redis)

    notifier = MediaWorkerNotifier(settings.telegram.bot_token.get_secret_value())
    logger.info("✅ Notifier ready")

    logger.info("🚀 media_worker ready, starting tasks")
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(whisper_model.unload_loop(), name="whisper-unload")
            tg.create_task(poll_loop(state, notifier), name="poll-loop")
    finally:
        await notifier.close()
        await asyncio.sleep(0.25)


if __name__ == "__main__":
    asyncio.run(main())
