from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from packages.app_state import AppState
from packages.services.category_service import CategoryService
from packages.services.recipe_service import RecipeService
from packages.services.user_service import UserService


class DependencyMiddleware(BaseMiddleware):
    """
    Инжектит доменные зависимости прямо в аргументы хендлеров (идиоматичный
    aiogram DI вместо PTB-овского god-object `context`).

    Хендлер объявляет ровно то, что ему нужно:
        async def handler(message: Message, recipe_service: RecipeService): ...

    `bot` aiogram прокидывает сам, поэтому здесь его не дублируем.
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state = self._app_state
        redis = state.redis
        if redis is None:
            raise RuntimeError("Redis не инициализирован в AppState")

        data["redis"] = redis
        data["recipe_service"] = RecipeService(state.db, redis)
        data["category_service"] = CategoryService(state.db, redis)
        data["user_service"] = UserService(state.db, redis)
        return await handler(event, data)
