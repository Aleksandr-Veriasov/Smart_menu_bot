import json

from redis.asyncio import Redis

from packages.redis import ttl
from packages.redis.keys import RedisKeys


class ProgressMessageCacheRepository:

    @classmethod
    async def get(cls, r: Redis, user_id: int) -> dict | None:
        """Возвращает данные прогресс-сообщения или None."""
        raw = await r.get(RedisKeys.user_progress_message(user_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @classmethod
    async def set(cls, r: Redis, user_id: int, payload: dict) -> None:
        """Сохраняет данные прогресс-сообщения."""
        value = json.dumps(payload, ensure_ascii=False)
        await r.setex(
            RedisKeys.user_progress_message(user_id),
            ttl.RECIPE_ACTION,
            value,
        )

    @classmethod
    async def delete(cls, r: Redis, user_id: int) -> None:
        """Удаляет данные прогресс-сообщения."""
        await r.delete(RedisKeys.user_progress_message(user_id))
