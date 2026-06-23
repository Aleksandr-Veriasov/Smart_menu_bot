import logging

from packages.redis.repository.base import BaseRedisRepository

logger = logging.getLogger(__name__)


class UserCacheRepository(BaseRedisRepository):

    async def get_exists(self, user_id: int) -> bool | None:
        """
        Проверить наличие флага 'пользователь существует'.
        Возвращает:
          - True, если флаг есть
          - None, если ключа нет
        """
        raw = await self.redis.get(self.keys.user_exists(user_id=user_id))
        return True if raw is not None else None

    async def set_exists(self, user_id: int) -> None:
        """Установить флаг 'пользователь существует'."""
        await self.redis.setex(self.keys.user_exists(user_id=user_id), self.ttl.USER_EXISTS, "1")
        logger.debug(f"✅ Флаг существования пользователя {user_id} сохранён в кэше")

    async def invalidate_exists(self, user_id: int) -> None:
        """Удалить флаг 'пользователь существует'."""
        await self.redis.delete(self.keys.user_exists(user_id=user_id))
