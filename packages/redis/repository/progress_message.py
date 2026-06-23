import json

from packages.redis.repository.base import BaseRedisRepository


class ProgressMessageCacheRepository(BaseRedisRepository):

    async def get(self, user_id: int) -> dict | None:
        """Возвращает данные прогресс-сообщения или None."""
        raw = await self.redis.get(self.keys.user_progress_message(user_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def set(self, user_id: int, payload: dict) -> None:
        """Сохраняет данные прогресс-сообщения."""
        value = json.dumps(payload, ensure_ascii=False)
        await self.redis.setex(
            self.keys.user_progress_message(user_id),
            self.ttl.RECIPE_ACTION,
            value,
        )

    async def delete(self, user_id: int) -> None:
        """Удаляет данные прогресс-сообщения."""
        await self.redis.delete(self.keys.user_progress_message(user_id))
