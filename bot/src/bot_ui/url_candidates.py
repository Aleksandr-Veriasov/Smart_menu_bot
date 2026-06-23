from redis.asyncio import Redis

from packages.redis.repository import UrlCandidateCacheRepository


class UrlCandidateStore:
    """Хранилище состояния выбора рецепта по ссылке для конкретного пользователя."""

    def __init__(self, redis: Redis, user_id: int) -> None:
        self.redis = redis
        self.user_id = user_id
        self._repo = UrlCandidateCacheRepository

    async def get(self, *, sid: str) -> dict | None:
        """Возвращает состояние кандидата по идентификатору сессии или None."""
        return await self._repo.get(self.redis, user_id=self.user_id, sid=sid)

    async def set(self, *, sid: str, payload: dict) -> None:
        """Сохраняет состояние кандидата."""
        await self._repo.set(self.redis, user_id=self.user_id, sid=sid, payload=payload)

    async def set_merge(self, *, sid: str, patch: dict) -> None:
        """Обновляет отдельные поля состояния кандидата, не затрагивая остальные."""
        await self._repo.set_merge(self.redis, user_id=self.user_id, sid=sid, patch=patch)

    async def delete(self, *, sid: str) -> None:
        """Удаляет состояние кандидата после завершения сценария выбора рецепта."""
        await self._repo.delete(self.redis, user_id=self.user_id, sid=sid)
