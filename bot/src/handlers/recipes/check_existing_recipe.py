import logging

from aiogram.enums import ParseMode
from aiogram.types import Message
from redis.asyncio import Redis

from bot.src.handlers.recipes.existing_by_url import (
    maybe_handle_multiple_existing_recipes,
)
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import add_recipe_keyboard
from bot.src.utils.messaging import answer_and_track, answer_video_and_track
from bot.src.utils.recipe_text import build_existing_recipe_text
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

EXISTING_RECIPE_VIDEOS_LIMIT = 20


async def handle_existing_recipe(
    message: Message,
    recipe_service: RecipeService,
    redis: Redis,
    url: str,
) -> bool:
    """
    Проверяет, существует ли рецепт с данным URL, и отправляет его пользователю.
    Возвращает True, если рецепт найден и отправлен, иначе False.
    """
    user_id = message.from_user.id if message.from_user else None
    match = await recipe_service.find_existing_by_url(url, user_id, limit=EXISTING_RECIPE_VIDEOS_LIMIT)

    if not match.recipe_ids:
        return False

    # Несколько рецептов по одному URL — передаём управление в сценарий выбора.
    if len(match.recipe_ids) >= 2:
        return await maybe_handle_multiple_existing_recipes(
            message=message,
            recipe_service=recipe_service,
            redis=redis,
            original_url=url,
            candidates=match.recipe_ids,
        )

    recipe = match.recipe
    if recipe is None:
        return False

    recipe_id = match.recipe_ids[0]
    text = build_existing_recipe_text(recipe)

    # Сначала отправляем видео, если оно есть.
    if match.video_url:
        await answer_video_and_track(message, redis, match.video_url, user_id=user_id)

    # Затем текст рецепта с подходящей клавиатурой.
    reply_markup = home_keyboard() if match.already_linked else add_recipe_keyboard(recipe_id)
    header = "Этот рецепт у Вас уже сохранён ✅" if match.already_linked else "Этот рецепт уже есть в нашем каталоге ✅"
    await answer_and_track(
        message,
        redis,
        f"{header}\n\n{text}",
        user_id=user_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )
    return True
