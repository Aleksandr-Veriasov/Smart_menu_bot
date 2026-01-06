import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import cast

from fastapi import FastAPI, HTTPException, Request
from prometheus_fastapi_instrumentator import Instrumentator
from telegram import Update
from telegram.ext import Application

from bot.app.core.types import AppState, PTBApp
from bot.app.handlers.setup import setup_handlers
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.db.migrate_and_seed import ensure_db_up_to_date
from packages.db.models import Base
from packages.logging_config import setup_logging
from packages.media.video_downloader import cleanup_old_videos
from packages.redis.redis_conn import close_redis, get_redis

setup_logging()
logger = logging.getLogger(__name__)


def build_state() -> AppState:
    return AppState(
        db=Database(
            db_url=settings.db.sqlalchemy_url(use_async=True),
            echo=settings.debug,
            pool_recycle=settings.db.pool_recycle,
            pool_pre_ping=settings.db.pool_pre_ping,
        ),
        cleanup_task=None,
    )


async def runtime_start(ptb_app: PTBApp, state: AppState) -> None:
    """
    Инициализация при старте приложения (PTB или FastAPI).
    Здесь можно запускать долгоживущие задачи, подключаться к БД и т.п.
    """
    logger.info("🚀 Запуск runtime инициализации…")
    # привяжем state к приложению, чтобы он был доступен хендлерам
    ptb_app.bot_data["state"] = state

    # Redis
    state.redis = await get_redis()
    pong = await state.redis.ping()
    logger.info("🧠 Redis подключён, PING=%s", pong)

    # Фоновая очистка
    logger.info("🚀 Запускаем фоновую задачу очистки видео…")
    state.cleanup_task = asyncio.create_task(cleanup_old_videos())

    # БД: bootstrap (по флагу) и healthcheck
    if settings.db.bootstrap_schema:
        await state.db.create_all(Base.metadata)
    ok = await state.db.healthcheck()
    if not ok:
        raise RuntimeError("DB healthcheck failed at startup")

    if settings.db.run_migrations_on_startup:
        sync_db_url = settings.db.sqlalchemy_url(use_async=False).render_as_string(hide_password=False)
        await ensure_db_up_to_date(sync_db_url)
        logger.info("Миграция выполнена")

    # Если включён режим вебхука — ставим вебхук (вариант А: авто)
    if settings.telegram.use_webhook:
        await ptb_app.bot.set_webhook(
            url=settings.webhooks.url(),
            secret_token=settings.webhooks.secret_token.get_secret_value(),
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "inline_query"],
        )
        logger.info("🔗 Webhook установлен")


async def runtime_stop(state: AppState) -> None:
    """
    Завершение при остановке приложения (PTB или FastAPI).
    Здесь можно останавливать долгоживущие задачи, отключаться от БД и т.п.
    """
    # Останавливаем фоновые задачи и закрываем ресурсы
    cur_state: AppState = state

    task: asyncio.Task[None] | None = cur_state.cleanup_task
    if task and not task.done():
        logger.info("⛔ Останавливаем фоновую задачу…")
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.info("✅ Фоновая задача остановлена.")

    # Закрыть Redis
    if cur_state.redis is not None:
        await close_redis()
        cur_state.redis = None
        logger.info("🔒 Redis соединения закрыты.")

    await cur_state.db.dispose()
    logger.info("🔒 Соединения БД закрыты.")


def create_ptb_app(attach_ptb_hooks: bool) -> PTBApp:
    """
    Создаёт и настраивает PTB Application.
    Если attach_ptb_hooks=True, то навешивает хуки старта/остановки PTB.
    Если attach_ptb_hooks=False, то хуки НЕ навешиваются (т.к. мы их
    реализуем в FastAPI).
    """
    token = settings.telegram.bot_token.get_secret_value().strip()
    if not token:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN пуст.")

    # Собираем PTB
    ptb_app = cast(PTBApp, Application.builder().token(token).build())
    setup_handlers(ptb_app)

    if attach_ptb_hooks:
        state = build_state()

        async def on_startup(app: PTBApp) -> None:
            await runtime_start(app, state)

        async def on_shutdown(app: PTBApp) -> None:
            await runtime_stop(state)

        ptb_app = cast(
            PTBApp,
            Application.builder().token(token).post_init(on_startup).post_shutdown(on_shutdown).build(),
        )
        setup_handlers(ptb_app)

    return ptb_app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Контекстный менеджер для инициализации и завершения FastAPI-приложения.
    Здесь же инициализируем PTB Application в режиме webhook.
    """
    logger.info("🚀 Запуск webhook-сервера FastAPI…")
    ptb_app: PTBApp = create_ptb_app(attach_ptb_hooks=False)
    state = build_state()

    await ptb_app.initialize()
    await runtime_start(ptb_app, state)
    await ptb_app.start()

    # сохраним в app.state, чтобы роуты имели доступ
    app.state.ptb_app = ptb_app
    app.state.state = state
    logger.info("✅ PTB Application запущен (webhook mode).")

    try:
        yield
    finally:
        logger.info("🛑 Остановка webhook-сервера…")
        await runtime_stop(state)
        await ptb_app.stop()
        await ptb_app.shutdown()
        app.state.ptb_app = None
        app.state.state = None


fastapi_app = FastAPI(title="Telegram Bot Webhook", lifespan=lifespan)
Instrumentator().instrument(fastapi_app).expose(fastapi_app, endpoint="/metrics", include_in_schema=False)


@fastapi_app.post(settings.webhooks.path())
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """
    Обработчик вебхука Telegram.
    PTB Application инициализируется в lifespan FastAPI-приложения
    и хранится в app.state.
    """
    ptb_app: PTBApp | None = getattr(request.app.state, "ptb_app", None)
    if ptb_app is None:
        raise HTTPException(status_code=503, detail="PTB not ready")

    # Проверка секрета от Telegram (защита от «левых» POST)
    secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_hdr != settings.webhooks.secret_token.get_secret_value():
        raise HTTPException(status_code=403, detail="Invalid secret token")

    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.update_queue.put(update)
    return {"ok": True}


if __name__ == "__main__":
    if not settings.telegram.use_webhook:
        # Классический режим: polling
        try:
            application = create_ptb_app(attach_ptb_hooks=True)
            logger.info("🤖 Бот запускается (polling)…")
            application.run_polling(
                poll_interval=1.0,
                drop_pending_updates=True,
            )
        except Exception:
            logger.exception("🔥 Ошибка при запуске бота (polling)")
            raise
    else:
        # Режим вебхука: поднимаем FastAPI-сервер внутри этого процесса
        import uvicorn

        port = settings.webhooks.port
        uvicorn.run(
            fastapi_app,
            host="0.0.0.0",
            port=port,
            # reload не нужен в контейнере
            workers=settings.fast_api.uvicorn_workers,
            log_level="info",
        )
