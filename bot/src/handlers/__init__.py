import logging

from aiogram import Dispatcher

from bot.src.handlers import user, video
from bot.src.handlers.recipes import (
    add_recipe,
    browse,
    delete_recipe,
    existing_by_url,
    pagination,
    save_recipe,
    search_recipes,
    share_link,
)

logger = logging.getLogger(__name__)


def setup_routers(dp: Dispatcher) -> None:
    """Регистрирует все роутеры в диспетчере."""

    logger.info("Регистрация роутеров...")
    # Команды и навигация (/start, /help, кнопка «На главную»).
    dp.include_router(user.router)

    # FSM-сценарии (состояние ограничивает обработчики подтверждений/ввода).
    dp.include_router(save_recipe.router)
    dp.include_router(delete_recipe.router)
    dp.include_router(search_recipes.router)

    # Добавление существующего рецепта к себе (recipe:add / addcat).
    dp.include_router(add_recipe.router)
    # Шаринг рецептов (recipe:share / shareback).
    dp.include_router(share_link.router)
    # Выбор рецепта по ссылке, если по URL найдено несколько (url:*).
    dp.include_router(existing_by_url.router)

    # Просмотр: меню/книга/категории/карточка рецепта.
    dp.include_router(browse.router)
    # Пагинация списков рецептов (page:*).
    dp.include_router(pagination.router)

    # Приём ссылок на видео (самый «широкий» текстовый хендлер — последним).
    dp.include_router(video.router)
    logger.info("Все роутеры зарегистрированы.")


__all__ = ["setup_routers"]
