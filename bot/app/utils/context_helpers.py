from redis.asyncio import Redis

from bot.app.core.types import AppState, PTBContext


def _get_app_state(context: PTBContext) -> AppState:
    state = context.bot_data.get("state")
    if not isinstance(state, AppState):
        raise RuntimeError("Некорректный или отсутствующий AppState в bot_data.")
    return state


def get_redis_cli(context: PTBContext) -> Redis:
    state = _get_app_state(context)
    if state.redis is None:
        raise RuntimeError("Redis не инициализирован.")
    return state.redis
