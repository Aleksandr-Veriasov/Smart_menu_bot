from redis.asyncio import Redis

from packages.redis.data_models import UserMessageIds
from packages.redis.repository import UserMessageIdsCacheRepository


class MessageIdsStore:
    """Хранилище message_id, которые бот позже удаляет или схлопывает."""

    def __init__(self, redis: Redis, user_id: int) -> None:
        """Создаёт store для UI message_id конкретного пользователя."""
        self._repo = UserMessageIdsCacheRepository(redis)
        self.user_id = user_id

    async def get(self) -> UserMessageIds | None:
        """Возвращает сохранённые message_id пользователя или None."""
        return await self._repo.get_user_message_ids(self.user_id)

    async def append(self, *, chat_id: int, message_ids: list[int]) -> None:
        """Добавляет message_id к текущему UI-трекингу пользователя."""
        await self._repo.append_user_message_ids(self.user_id, chat_id=chat_id, message_ids=message_ids)

    async def set(self, *, chat_id: int, message_ids: list[int]) -> None:
        """Перезаписывает UI-трекинг пользователя заданным списком message_id."""
        await self._repo.set_user_message_ids(self.user_id, chat_id=chat_id, message_ids=message_ids)

    async def clear(self) -> None:
        """Удаляет UI-трекинг message_id пользователя."""
        await self._repo.clear_user_message_ids(self.user_id)
