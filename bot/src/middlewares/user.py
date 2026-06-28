from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, User

from packages.db.schemas import UserCreate
from packages.services.user_service import UserService


class UserMiddleware(BaseMiddleware):
    """
    Достаёт пользователя из апдейта, гарантирует запись в БД и кладёт данные в DI.

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

        user_recipe_count: int | None = None
        user_service = data.get("user_service")
        if user is not None and isinstance(user_service, UserService):
            await user_service.ensure_user_exists(
                UserCreate(
                    id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                )
            )
            user_recipe_count = await user_service.get_recipe_count(user.id)
        data["user_recipe_count"] = user_recipe_count
        return await handler(event, data)
