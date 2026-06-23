import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from prometheus_fastapi_instrumentator import Instrumentator

from bot.src.handlers import setup_routers
from bot.src.middlewares.deps import DependencyMiddleware
from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.backup import run_daily_dump_scheduler
from packages.db.database import Database
from packages.db.migrate_and_seed import ensure_db_up_to_date
from packages.db.models import Base
from packages.logging_config import notify_startup, setup_logging
from packages.media.video_downloader import cleanup_old_videos
from packages.redis.redis_conn import close_redis, get_redis

setup_logging()
logger = logging.getLogger(__name__)

ALLOWED_UPDATES = ["message", "callback_query", "inline_query"]


def build_state() -> AppState:
    return AppState(
        db=Database(
            db_url=settings.db.sqlalchemy_url(use_async=True),
            echo=settings.debug,
            pool_recycle=settings.db.pool_recycle,
            pool_pre_ping=settings.db.pool_pre_ping,
        ),
        cleanup_task=None,
        backup_task=None,
    )


def build_bot() -> Bot:
    """Создаёт экземпляр aiogram Bot."""
    token = settings.telegram.bot_token.get_secret_value().strip()
    if not token:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN пуст.")
    return Bot(token=token)


def build_dispatcher(state: AppState) -> Dispatcher:
    """
    Создаёт и настраивает aiogram Dispatcher.

    FSM-состояния хранятся в Redis, доменные зависимости (сервисы/redis)
    инжектятся в аргументы хендлеров через DependencyMiddleware.
    """
    storage = RedisStorage.from_url(settings.redis.dsn())
    dp = Dispatcher(storage=storage)
    # DI: сервисы/redis инжектятся прямо в аргументы хендлеров (bot aiogram даёт сам).
    dp.update.outer_middleware(DependencyMiddleware(state))
    setup_routers(dp)
    return dp


async def runtime_start(bot: Bot, state: AppState) -> None:
    """
    Инициализация при старте приложения (polling или FastAPI).
    Здесь можно запускать долгоживущие задачи, подключаться к БД и т.п.
    """
    logger.info("🚀 Запуск runtime инициализации…")

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

    # Плановый дамп БД (ежедневно по UTC)
    logger.info("🚀 Запускаем планировщик дампов БД…")
    state.backup_task = asyncio.create_task(run_daily_dump_scheduler())

    # Если включён режим вебхука — ставим вебхук (вариант А: авто)
    if settings.telegram.use_webhook:
        await bot.set_webhook(
            url=settings.webhooks.url(),
            secret_token=settings.webhooks.secret_token.get_secret_value(),
            drop_pending_updates=True,
            allowed_updates=ALLOWED_UPDATES,
        )
        logger.info("🔗 Webhook установлен")

    notify_startup("SmartMenuBot")


async def runtime_stop(state: AppState) -> None:
    """
    Завершение при остановке приложения (polling или FastAPI).
    Здесь можно останавливать долгоживущие задачи, отключаться от БД и т.п.
    """
    cur_state: AppState = state

    task: asyncio.Task[None] | None = cur_state.cleanup_task
    if task and not task.done():
        logger.info("⛔ Останавливаем фоновую задачу…")
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        logger.info("✅ Фоновая задача остановлена.")

    backup_task: asyncio.Task[None] | None = cur_state.backup_task
    if backup_task and not backup_task.done():
        logger.info("⛔ Останавливаем планировщик дампов…")
        backup_task.cancel()
        with suppress(asyncio.CancelledError):
            await backup_task
        logger.info("✅ Планировщик дампов остановлен.")

    # Закрыть Redis
    if cur_state.redis is not None:
        await close_redis()
        cur_state.redis = None
        logger.info("🔒 Redis соединения закрыты.")

    await cur_state.db.dispose()
    logger.info("🔒 Соединения БД закрыты.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Контекстный менеджер инициализации/завершения FastAPI-приложения.
    Здесь же поднимаем aiogram Bot/Dispatcher в режиме webhook.
    """
    logger.info("🚀 Запуск webhook-сервера FastAPI…")
    state = build_state()
    bot = build_bot()
    dp = build_dispatcher(state)

    await runtime_start(bot, state)

    # сохраним в app.state, чтобы роуты имели доступ
    app.state.bot = bot
    app.state.dp = dp
    app.state.state = state
    logger.info("✅ aiogram-приложение запущено (режим webhook).")

    try:
        yield
    finally:
        logger.info("🛑 Остановка webhook-сервера…")
        await runtime_stop(state)
        with suppress(Exception):
            await bot.session.close()
        app.state.bot = None
        app.state.dp = None
        app.state.state = None


fastapi_app = FastAPI(title="Webhook Telegram-бота", lifespan=lifespan)
Instrumentator().instrument(fastapi_app).expose(fastapi_app, endpoint="/metrics", include_in_schema=False)


@fastapi_app.post(settings.webhooks.path())
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """
    Обработчик вебхука Telegram.
    aiogram Bot/Dispatcher инициализируются в lifespan FastAPI-приложения
    и хранятся в app.state.
    """
    bot: Bot | None = getattr(request.app.state, "bot", None)
    dp: Dispatcher | None = getattr(request.app.state, "dp", None)
    if bot is None or dp is None:
        raise HTTPException(status_code=503, detail="Бот ещё не готов")

    # Проверка секрета от Telegram (защита от «левых» POST)
    secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_hdr != settings.webhooks.secret_token.get_secret_value():
        raise HTTPException(status_code=403, detail="Некорректный secret token")

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


async def run_polling() -> None:
    """Классический режим: long-polling."""
    state = build_state()
    bot = build_bot()
    dp = build_dispatcher(state)

    @dp.startup()
    async def _on_startup() -> None:
        await runtime_start(bot, state)

    @dp.shutdown()
    async def _on_shutdown() -> None:
        await runtime_stop(state)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🤖 Бот запускается (polling)…")
    try:
        await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        with suppress(Exception):
            await bot.session.close()


if __name__ == "__main__":
    if not settings.telegram.use_webhook:
        try:
            asyncio.run(run_polling())
        except (KeyboardInterrupt, SystemExit):
            logger.info("Бот остановлен.")
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
            workers=settings.fast_api.uvicorn_workers,
            log_level="info",
        )
