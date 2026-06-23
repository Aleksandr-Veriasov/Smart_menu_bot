import json

from redis.asyncio import Redis

from packages.redis import ttl
from packages.redis.keys import RedisKeys


class RecipeActionCacheRepository:

    @classmethod
    async def get(cls, r: Redis, user_id: int, action: str) -> dict | None:
        """Возвращает payload действия или None."""
        raw = await r.get(RedisKeys.user_recipe_action(user_id, action))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @classmethod
    async def set(cls, r: Redis, user_id: int, action: str, payload: dict) -> None:
        """Сохраняет payload действия."""
        value = json.dumps(payload, ensure_ascii=False)
        await r.setex(RedisKeys.user_recipe_action(user_id, action), ttl.RECIPE_ACTION, value)

    @classmethod
    async def delete(cls, r: Redis, user_id: int, action: str) -> None:
        """Удаляет payload действия."""
        await r.delete(RedisKeys.user_recipe_action(user_id, action))

    @classmethod
    async def delete_all(cls, r: Redis, user_id: int) -> None:
        """Удаляет все действия пользователя."""
        for action in ("recipes_state", "edit", "delete", "change_category"):
            await cls.delete(r, user_id, action)
