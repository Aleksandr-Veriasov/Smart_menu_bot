from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, User


class UserMiddleware(BaseMiddleware):
    """
    Достаёт пользователя из апдейта и кладёт его в data["user"].

    Так хендлерам не нужно каждый раз доставать `message.from_user` /
    `callback.from_user` — они объявляют `user: User` в аргументах.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None and isinstance(event, Update) and event.event is not None:
            user = getattr(event.event, "from_user", None)
        data["user"] = user
        return await handler(event, data)
