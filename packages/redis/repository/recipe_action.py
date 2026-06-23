import json

from packages.redis.repository.base import BaseRedisRepository


class RecipeActionCacheRepository(BaseRedisRepository):

    async def get(self, user_id: int, action: str) -> dict | None:
        """Возвращает payload действия или None."""
        raw = await self.redis.get(self.keys.user_recipe_action(user_id, action))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def set(self, user_id: int, action: str, payload: dict) -> None:
        """Сохраняет payload действия."""
        value = json.dumps(payload, ensure_ascii=False)
        await self.redis.setex(self.keys.user_recipe_action(user_id, action), self.ttl.RECIPE_ACTION, value)

    async def delete(self, user_id: int, action: str) -> None:
        """Удаляет payload действия."""
        await self.redis.delete(self.keys.user_recipe_action(user_id, action))

    async def delete_all(self, user_id: int) -> None:
        """Удаляет все действия пользователя."""
        for action in ("recipes_state", "edit", "delete", "change_category"):
            await self.delete(user_id, action)
