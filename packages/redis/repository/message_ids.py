import json

from packages.redis.data_models import UserMessageIds
from packages.redis.repository.base import BaseRedisRepository


class UserMessageIdsCacheRepository(BaseRedisRepository):

    async def get_user_message_ids(self, user_id: int) -> UserMessageIds | None:
        """Вернёт chat_id и message_ids пользователя или None."""
        raw = await self.redis.get(self.keys.user_last_recipe_messages(user_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "chat_id" in data and "message_ids" in data:
                chat_id = data.get("chat_id")
                message_ids = data.get("message_ids")
                if (
                    isinstance(chat_id, int)
                    and isinstance(message_ids, list)
                    and all(isinstance(x, int) for x in message_ids)
                ):
                    return UserMessageIds(chat_id=chat_id, message_ids=message_ids)
        except Exception:
            pass
        return None

    async def append_user_message_ids(self, user_id: int, chat_id: int, message_ids: list[int]) -> None:
        """Добавляет message_ids к существующим для пользователя."""
        existing = await self.get_user_message_ids(user_id)
        if existing and existing.chat_id == int(chat_id):
            ids = [int(i) for i in existing.message_ids if isinstance(i, int)]
        else:
            ids = []
        ids.extend([int(i) for i in message_ids if isinstance(i, int)])
        payload = json.dumps({"chat_id": int(chat_id), "message_ids": ids}, ensure_ascii=False)
        await self.redis.set(self.keys.user_last_recipe_messages(user_id), payload)

    async def set_user_message_ids(self, user_id: int, chat_id: int, message_ids: list[int]) -> None:
        """Перезаписывает message_ids пользователя."""
        ids = [int(i) for i in message_ids if isinstance(i, int)]
        payload = json.dumps({"chat_id": int(chat_id), "message_ids": ids}, ensure_ascii=False)
        await self.redis.set(self.keys.user_last_recipe_messages(user_id), payload)

    async def clear_user_message_ids(self, user_id: int) -> None:
        """Удаляет message_ids пользователя."""
        await self.redis.delete(self.keys.user_last_recipe_messages(user_id))
