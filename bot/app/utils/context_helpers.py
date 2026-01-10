from redis.asyncio import Redis

from bot.app.core.types import AppState, PTBContext
from packages.db.database import Database


def get_db(context: PTBContext) -> Database:
    """
    Извлекает объект базы данных из состояния приложения.
    Если состояние некорректно, вызывает RuntimeError.
    """
    state = context.application.bot_data.get("state")
    if not isinstance(state, AppState):
        raise RuntimeError("Некорректный или отсутствующий AppState в bot_data.")
    return state.db


def get_redis_cli(context: PTBContext) -> Redis:
    """
    Безопасно извлекает Redis из AppState, лежащего в bot_data.
    """
    state = context.bot_data.get("state")
    if not isinstance(state, AppState) or state.redis is None:
        raise RuntimeError("Некорректный AppState или Redis не инициализирован.")
    return state.redis


def get_db_and_redis(context: PTBContext) -> tuple[Database, Redis]:
    """
    Возвращает (db, redis) из AppState.
    """
    db = get_db(context)
    redis = get_redis_cli(context)
    return db, redis
