import asyncio
import logging
import os

from media_worker.notifications.notifier import MediaWorkerNotifier
from media_worker.worker import pipeline
from packages.app_state import AppState
from packages.services.pipeline_service import PipelineService
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

_POLL_INTERVAL = float(os.getenv("MEDIA_WORKER_POLL_INTERVAL", "3"))  # секунд


async def process_one(
    job_id: int,
    *,
    state: AppState,
    notifier: MediaWorkerNotifier,
) -> None:
    pipeline_service = PipelineService(state.db, state.redis)
    recipe_service = RecipeService(state.db, state.redis)

    job = await pipeline_service.get_by_id(job_id)
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
        await pipeline_service.ack(job_id)
        logger.info("job_id=%s — ack", job_id)
    except Exception as exc:
        await pipeline_service.nack(job_id, error=str(exc))
        logger.warning("job_id=%s — nack: %s", job_id, exc)


async def poll_loop(state: AppState, notifier: MediaWorkerNotifier) -> None:
    logger.info("media_worker polling started (interval=%.1fs)", _POLL_INTERVAL)
    while True:
        try:
            pipeline_service = PipelineService(state.db, state.redis)
            job_ids = await pipeline_service.claim(batch_size=1)

            for job_id in job_ids:
                logger.info("Claimed job_id=%s", job_id)
                await process_one(job_id, state=state, notifier=notifier)

            if not job_ids:
                await asyncio.sleep(_POLL_INTERVAL)

        except Exception:
            logger.exception("Ошибка в polling loop, перезапускаем через %.1fs", _POLL_INTERVAL)
            await asyncio.sleep(_POLL_INTERVAL)
