"""Composition root: сборка Bot и Dispatcher."""

from datetime import timedelta

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from bot.src.handlers import setup_routers
from bot.src.middlewares.deps import DependencyMiddleware
from bot.src.middlewares.store import StoreMiddleware
from bot.src.middlewares.user import UserMiddleware
from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.redis.redis_conn import get_redis

# Время жизни FSM-состояния и данных диалога в Redis (протухание брошенных диалогов).
FSM_TTL = timedelta(hours=24)


def build_state() -> AppState:
    """Создаёт контейнер общего состояния приложения."""
    return AppState(
        db=Database(
            db_url=settings.db.sqlalchemy_url(use_async=True),
            echo=settings.debug,
            pool_recycle=settings.db.pool_recycle,
            pool_pre_ping=settings.db.pool_pre_ping,
            pool_size=3,
            max_overflow=3,
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


async def build_dispatcher(state: AppState) -> Dispatcher:
    """
    Создаёт и настраивает aiogram Dispatcher.

    FSM-состояния хранятся в Redis (тот же пул, что и `get_redis()`, с TTL на
    протухание брошенных диалогов); доменные зависимости (сервисы/redis) и
    пользователь инжектятся в аргументы хендлеров через middleware.
    """
    storage = RedisStorage(redis=await get_redis(), state_ttl=FSM_TTL, data_ttl=FSM_TTL)
    dp = Dispatcher(storage=storage)
    # DI: сервисы/redis инжектятся прямо в аргументы хендлеров (bot aiogram даёт сам).
    dp.update.outer_middleware(DependencyMiddleware(state))
    # Пользователь из апдейта кладётся в data["user"].
    dp.update.outer_middleware(UserMiddleware())
    # UI-сервисы собираются после пользователя, чтобы message_id хранились по user_id.
    dp.update.outer_middleware(StoreMiddleware())
    setup_routers(dp)
    return dp
