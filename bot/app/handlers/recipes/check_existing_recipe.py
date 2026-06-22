import logging

from telegram import Update
from telegram.constants import ParseMode

from bot.app.core.types import PTBContext
from bot.app.handlers.recipes.existing_by_url import (
    maybe_handle_multiple_existing_recipes,
)
from bot.app.keyboards.inlines import add_recipe_keyboard, home_keyboard
from bot.app.utils.message_cache import reply_text_and_cache, reply_video_and_cache
from bot.app.utils.message_utils import build_existing_recipe_text

logger = logging.getLogger(__name__)

EXISTING_RECIPE_VIDEOS_LIMIT = 20


async def handle_existing_recipe(update: Update, context: PTBContext, url: str) -> bool:
    """
    Проверяет, существует ли рецепт с данным URL, и отправляет его пользователю.
    Возвращает True, если рецепт найден и отправлен, иначе False.
    """
    message = update.effective_message
    if not message:
        return False

    user_id = message.from_user.id if message.from_user else None
    match = await context.recipe_service.find_existing_by_url(url, user_id, limit=EXISTING_RECIPE_VIDEOS_LIMIT)

    if not match.recipe_ids:
        return False

    # Несколько рецептов по одному URL — передаём управление в сценарий выбора.
    if len(match.recipe_ids) >= 2:
        return await maybe_handle_multiple_existing_recipes(
            update=update,
            context=context,
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
        await reply_video_and_cache(message, context, match.video_url)

    # Затем текст рецепта с подходящей клавиатурой.
    reply_markup = home_keyboard() if match.already_linked else add_recipe_keyboard(recipe_id)
    header = "Этот рецепт у Вас уже сохранён ✅" if match.already_linked else "Этот рецепт уже есть в нашем каталоге ✅"
    await reply_text_and_cache(
        message,
        context,
        f"{header}\n\n{text}",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )
    return True
