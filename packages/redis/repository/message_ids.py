import json

from redis.asyncio import Redis

from packages.redis.data_models import UserMessageIds
from packages.redis.keys import RedisKeys


class UserMessageIdsCacheRepository:

    @classmethod
    async def get_user_message_ids(cls, r: Redis, user_id: int) -> UserMessageIds | None:
        """Вернёт chat_id и message_ids пользователя или None."""
        raw = await r.get(RedisKeys.user_last_recipe_messages(user_id))
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

    @classmethod
    async def append_user_message_ids(cls, r: Redis, user_id: int, chat_id: int, message_ids: list[int]) -> None:
        """Добавляет message_ids к существующим для пользователя."""
        existing = await cls.get_user_message_ids(r, user_id)
        if existing and existing.chat_id == int(chat_id):
            ids = [int(i) for i in existing.message_ids if isinstance(i, int)]
        else:
            ids = []
        ids.extend([int(i) for i in message_ids if isinstance(i, int)])
        payload = json.dumps({"chat_id": int(chat_id), "message_ids": ids}, ensure_ascii=False)
        await r.set(RedisKeys.user_last_recipe_messages(user_id), payload)

    @classmethod
    async def set_user_message_ids(cls, r: Redis, user_id: int, chat_id: int, message_ids: list[int]) -> None:
        """Перезаписывает message_ids пользователя."""
        ids = [int(i) for i in message_ids if isinstance(i, int)]
        payload = json.dumps({"chat_id": int(chat_id), "message_ids": ids}, ensure_ascii=False)
        await r.set(RedisKeys.user_last_recipe_messages(user_id), payload)

    @classmethod
    async def clear_user_message_ids(cls, r: Redis, user_id: int) -> None:
        """Удаляет message_ids пользователя."""
        await r.delete(RedisKeys.user_last_recipe_messages(user_id))
