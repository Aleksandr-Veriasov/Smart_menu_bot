from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from redis.asyncio import Redis

from bot.src.bot_ui.message_ids import MessageIdsStore
from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.pipeline_drafts import PipelineDraftStore
from bot.src.bot_ui.url_candidates import UrlCandidateStore


class StoreMiddleware(BaseMiddleware):
    """Создаёт UI-сервисы, завязанные на текущего Telegram-пользователя."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        redis = data.get("redis")
        if not isinstance(redis, Redis):
            raise RuntimeError("Redis не найден в DI data")

        user = data.get("user")
        user_id = user.id if isinstance(user, User) else None
        if user_id is not None:
            data["pipeline_draft_store"] = PipelineDraftStore(redis, user_id)
            data["url_candidate_store"] = UrlCandidateStore(redis, user_id)
            message_ids_store = MessageIdsStore(redis, user_id)
            data["message_ids_store"] = message_ids_store
            data["message_service"] = MessageService(message_ids_store)
        return await handler(event, data)
