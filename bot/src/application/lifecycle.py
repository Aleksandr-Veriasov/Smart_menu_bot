"""Жизненный цикл приложения: поднятие/гашение ресурсов и фоновых задач.

Не знает про конкретный транспорт (polling/webhook) — его переиспользуют оба.
"""

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot

from packages.app_state import AppState
from packages.background.video_cleanup import cleanup_old_videos
from packages.common_settings.settings import settings
from packages.db.backup import run_daily_dump_scheduler
from packages.logging_config import notify_startup
from packages.redis.redis_conn import close_redis, get_redis

logger = logging.getLogger(__name__)


async def runtime_start(bot: Bot, state: AppState, *, allowed_updates: list[str]) -> None:
    """
    Инициализация при старте приложения (polling или webhook).
    Поднимает Redis, фоновые задачи, проверяет/мигрирует БД, ставит вебхук.

    `allowed_updates` — набор типов апдейтов (см. `dp.resolve_used_update_types()`),
    используется при установке вебхука.
    """
    logger.info("🚀 Запуск runtime инициализации…")

    # Redis
    state.redis = await get_redis()
    pong = await state.redis.ping()
    logger.info("🧠 Redis подключён, PING=%s", pong)

    # БД: healthcheck
    if not await state.db.healthcheck():
        raise RuntimeError("Проверка соединения с БД не пройдена при старте")
    logger.info("🗄 БД подключена")

    # Фоновая очистка
    logger.info("🚀 Запускаем фоновую задачу очистки видео…")
    state.cleanup_task = asyncio.create_task(cleanup_old_videos())

    # Плановый дамп БД (ежедневно по UTC)
    logger.info("🚀 Запускаем планировщик дампов БД…")
    state.backup_task = asyncio.create_task(run_daily_dump_scheduler())

    # Если включён режим вебхука — ставим вебхук (вариант А: авто)
    if settings.telegram.use_webhook:
        await bot.set_webhook(
            url=settings.webhooks.url(),
            secret_token=settings.webhooks.secret_token.get_secret_value(),
            drop_pending_updates=True,
            allowed_updates=allowed_updates,
        )
        logger.info("🔗 Webhook установлен")

    with suppress(Exception):
        notify_startup("SmartMenuBot")


async def runtime_stop(state: AppState) -> None:
    """
    Завершение при остановке приложения (polling или webhook).
    Останавливает фоновые задачи и закрывает соединения.
    """
    task: asyncio.Task[None] | None = state.cleanup_task
    if task and not task.done():
        logger.info("⛔ Останавливаем фоновую задачу…")
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.info("✅ Фоновая задача остановлена.")

    backup_task: asyncio.Task[None] | None = state.backup_task
    if backup_task and not backup_task.done():
        logger.info("⛔ Останавливаем планировщик дампов…")
        backup_task.cancel()
        with suppress(asyncio.CancelledError):
            await backup_task
        logger.info("✅ Планировщик дампов остановлен.")

    # Закрыть Redis
    if state.redis is not None:
        await close_redis()
        state.redis = None
        logger.info("🔒 Redis соединения закрыты.")

    await state.db.dispose()
    logger.info("🔒 Соединения БД закрыты.")
