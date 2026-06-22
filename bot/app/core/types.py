from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeAlias, TypedDict

from redis.asyncio import Redis
from telegram.ext import Application, CallbackContext, ExtBot, JobQueue

from packages.app_state import AppState

if TYPE_CHECKING:
    from packages.services.category_service import CategoryService
    from packages.services.recipe_service import RecipeService
    from packages.services.user_service import UserService


class BotData(TypedDict):
    state: AppState


class AppContext(
    CallbackContext[
        ExtBot[None],
        dict[Any, Any],
        dict[Any, Any],
        BotData,
    ]
):
    """
    Контекст PTB с доступом к общему состоянию приложения и сервисам.

    Сервисы отдаются как property — хендлерам не нужно доставать db/redis и
    конструировать сервис вручную. Импорты сервисов ленивые (внутри property),
    чтобы избежать циклов импорта; сами сервисы дёшевы в создании.
    """

    @property
    def app_state(self) -> AppState:
        state = self.bot_data.get("state")
        if not isinstance(state, AppState):
            raise RuntimeError("AppState не инициализирован в bot_data")
        return state

    def _require_redis(self) -> Redis:
        redis = self.app_state.redis
        if redis is None:
            raise RuntimeError("Redis не инициализирован в AppState")
        return redis

    @property
    def recipe_service(self) -> RecipeService:
        from packages.services.recipe_service import RecipeService

        return RecipeService(self.app_state.db, self._require_redis())

    @property
    def category_service(self) -> CategoryService:
        from packages.services.category_service import CategoryService

        return CategoryService(self.app_state.db, self._require_redis())

    @property
    def user_service(self) -> UserService:
        from packages.services.user_service import UserService

        return UserService(self.app_state.db, self._require_redis())


# Имя сохранено для обратной совместимости: хендлеры аннотируют context как PTBContext.
PTBContext: TypeAlias = AppContext

PTBApp: TypeAlias = Application[
    ExtBot[None],
    PTBContext,
    dict[Any, Any],  # user_data
    dict[Any, Any],  # chat_data
    BotData,  # bot_data
    JobQueue[PTBContext],
]

__all__ = ["AppContext", "AppState", "BotData", "PTBContext", "PTBApp"]
