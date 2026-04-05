import json
from typing import Any

from telegram.ext import BasePersistence, PersistenceInput

from packages.redis.redis_conn import get_redis


class RedisConversationPersistence(BasePersistence[dict[Any, Any], dict[Any, Any], dict[Any, Any]]):
    """PTB persistence for conversation state stored in Redis with TTL."""

    KEY_PREFIX = "ptb:conversations"

    def __init__(self, ttl_seconds: int = 3600, update_interval: float = 30) -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=False,
                user_data=False,
                callback_data=False,
            ),
            update_interval=update_interval,
        )
        self.ttl_seconds = ttl_seconds

    @classmethod
    def _redis_key(cls, name: str) -> str:
        return f"{cls.KEY_PREFIX}:{name}"

    @staticmethod
    def _encode_conversation_key(key: tuple[int | str, ...]) -> str:
        return json.dumps(list(key), separators=(",", ":"), ensure_ascii=True)

    @staticmethod
    def _decode_conversation_key(value: str) -> tuple[int | str, ...]:
        raw = json.loads(value)
        return tuple(raw)

    async def get_user_data(self) -> dict[int, dict[Any, Any]]:
        return {}

    async def get_chat_data(self) -> dict[int, dict[Any, Any]]:
        return {}

    async def get_bot_data(self) -> dict[Any, Any]:
        return {}

    async def get_callback_data(self) -> None:
        return None

    async def get_conversations(self, name: str) -> dict[tuple[int | str, ...], object]:
        redis = await get_redis()
        values = await redis.hgetall(self._redis_key(name))
        conversations: dict[tuple[int | str, ...], object] = {}
        for key, state in values.items():
            conversations[self._decode_conversation_key(key)] = json.loads(state)
        return conversations

    async def update_conversation(self, name: str, key: tuple[int | str, ...], new_state: object | None) -> None:
        redis = await get_redis()
        redis_key = self._redis_key(name)
        field = self._encode_conversation_key(key)

        if new_state is None:
            await redis.hdel(redis_key, field)
            if await redis.hlen(redis_key) == 0:
                await redis.delete(redis_key)
            else:
                await redis.expire(redis_key, self.ttl_seconds)
            return

        await redis.hset(redis_key, field, json.dumps(new_state, separators=(",", ":"), ensure_ascii=True))
        await redis.expire(redis_key, self.ttl_seconds)

    async def update_user_data(self, user_id: int, data: dict[Any, Any]) -> None:
        return None

    async def update_chat_data(self, chat_id: int, data: dict[Any, Any]) -> None:
        return None

    async def update_bot_data(self, data: dict[Any, Any]) -> None:
        return None

    async def update_callback_data(self, data: object) -> None:
        return None

    async def drop_chat_data(self, chat_id: int) -> None:
        return None

    async def drop_user_data(self, user_id: int) -> None:
        return None

    async def refresh_user_data(self, user_id: int, user_data: dict[Any, Any]) -> None:
        return None

    async def refresh_chat_data(self, chat_id: int, chat_data: dict[Any, Any]) -> None:
        return None

    async def refresh_bot_data(self, bot_data: dict[Any, Any]) -> None:
        return None

    async def flush(self) -> None:
        return None
