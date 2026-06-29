import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.tasks.broadcast import run_broadcast_worker
from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.migrate_and_seed import ensure_admin
from packages.db.pool_metrics import register_pool_metrics
from packages.redis.redis_conn import close_redis, get_redis

logger = logging.getLogger(__name__)


def build_lifespan(state: AppState):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.app_state = state

        register_pool_metrics(state.db.engine, service="backend")

        state.redis = await get_redis()
        ping = await state.redis.ping()
        logger.info(f"🧠 Redis подключён PING={ping}")

        logger.info("БД загружена")
        await ensure_admin(state.db)

        if settings.broadcast.enabled:
            state.broadcast_task = asyncio.create_task(run_broadcast_worker(state))

        try:
            yield
        finally:
            task = getattr(state, "broadcast_task", None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            if state.redis is not None:
                await close_redis()
                state.redis = None
                logger.info("🔒 Redis закрыт.")
            await state.db.engine.dispose()

    return lifespan
