"""media_worker — polling loop.

Цикл:
  1. claim job из pipeline_jobs (FOR UPDATE SKIP LOCKED)
  2. pipeline.run(job) — скачать / транскрибировать / сохранить / уведомить
  3. ack (успех) или nack (ошибка, backoff/failed)

Фоновая задача: whisper_model.unload_loop() — выгружает модель после TTL простоя.
"""

import asyncio
import logging
import os

from media_worker import pipeline, whisper_model
from media_worker.notifier import MediaWorkerNotifier
from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.db.repository import PipelineJobRepository
from packages.logging_config import setup_logging
from packages.redis.redis_conn import get_redis
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

_POLL_INTERVAL = float(os.getenv("MEDIA_WORKER_POLL_INTERVAL", "3"))  # секунд


async def _process_one(
    job_id: int,
    *,
    state: AppState,
    notifier: MediaWorkerNotifier,
) -> None:
    """Обработать один job: pipeline → ack/nack."""
    assert state.redis is not None
    recipe_service = RecipeService(state.db, state.redis)

    async with state.db.session() as session:
        repo = PipelineJobRepository(session)
        job = await repo.get_by_id(job_id)
        if job is None:
            logger.warning("job_id=%s не найден после claim", job_id)
            return

        try:
            await pipeline.run(
                job,
                recipe_service=recipe_service,
                redis=state.redis,
                notifier=notifier,
            )
            await repo.ack(job_id)
            await session.commit()
            logger.info("job_id=%s — ack", job_id)
        except Exception as exc:
            await repo.nack(job_id, error=str(exc))
            await session.commit()
            logger.warning("job_id=%s — nack: %s", job_id, exc)


async def _poll_loop(state: AppState, notifier: MediaWorkerNotifier) -> None:
    """Основной цикл: claim → process → ack/nack."""
    logger.info("media_worker polling started (interval=%.1fs)", _POLL_INTERVAL)
    while True:
        try:
            async with state.db.session() as session:
                jobs = await PipelineJobRepository(session).claim(batch_size=1)
                await session.commit()

            for job in jobs:
                logger.info("Claimed job_id=%s", job.id)
                await _process_one(int(job.id), state=state, notifier=notifier)

            if not jobs:
                await asyncio.sleep(_POLL_INTERVAL)

        except Exception:
            logger.exception("Ошибка в polling loop, перезапускаем через %.1fs", _POLL_INTERVAL)
            await asyncio.sleep(_POLL_INTERVAL)


async def main() -> None:
    setup_logging()
    logger.info("media_worker starting…")

    db = Database(settings.db.sqlalchemy_url(use_async=True))
    logger.info("✅ Database connected")

    redis = await get_redis()
    logger.info("✅ Redis connected")

    state = AppState(db=db, redis=redis)

    notifier = MediaWorkerNotifier(settings.telegram.bot_token.get_secret_value())
    logger.info("✅ Notifier ready")

    logger.info("🚀 media_worker ready, starting tasks")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(whisper_model.unload_loop(), name="whisper-unload")
        tg.create_task(_poll_loop(state, notifier), name="poll-loop")


if __name__ == "__main__":
    asyncio.run(main())
