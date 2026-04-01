from redis.asyncio import Redis

from bot.app.core.types import AppState, PTBContext
from packages.db.database import Database


def get_app_state(context: PTBContext) -> AppState:
    """
    Извлекает состояние приложения из bot_data.
    Если состояние некорректно, вызывает RuntimeError.
    """
    state = context.bot_data.get("state")
    if not isinstance(state, AppState):
        raise RuntimeError("Некорректный или отсутствующий AppState в bot_data.")
    return state


def get_db(context: PTBContext) -> Database:
    """
    Извлекает объект базы данных из состояния приложения.
    """
    state = get_app_state(context)
    if state.db is None:
        raise RuntimeError("Некорректный AppState или база данных не инициализирована.")
    return state.db


def get_redis_cli(context: PTBContext) -> Redis:
    """
    Безопасно извлекает Redis из AppState, лежащего в bot_data.
    """
    state = get_app_state(context)
    if state.redis is None:
        raise RuntimeError("Некорректный AppState или Redis не инициализирован.")
    return state.redis


def get_db_and_redis(context: PTBContext) -> tuple[Database, Redis]:
    """
    Возвращает (db, redis) из AppState.
    """
    state = get_app_state(context)
    if state.redis is None:
        raise RuntimeError("Некорректный AppState или Redis не инициализирован.")
    return state.db, state.redis
