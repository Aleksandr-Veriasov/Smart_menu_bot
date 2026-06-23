from aiogram.enums import ParseMode
from aiogram.types import Message

from bot.src.bot_ui.messages import MessageService
from bot.src.keyboards.recipe import add_recipe_keyboard
from bot.src.utils.recipe_text import build_existing_recipe_text
from bot.src.utils.share_token import decrypt_recipe_id
from packages.services.recipe_service import RecipeService


async def show_shared_recipe(
    message: Message,
    recipe_service: RecipeService,
    message_service: MessageService,
    token: str,
) -> bool:
    """Показывает рецепт по deep-link-токену. Возвращает True, если рецепт найден."""
    recipe_id = decrypt_recipe_id(token)
    if not recipe_id or not recipe_id.isdigit():
        return False

    recipe = await recipe_service.get_recipe_with_details(int(recipe_id))
    if not recipe:
        return False

    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        await message_service.answer_video_and_track(message, video_url)
    await message_service.answer_and_track(
        message,
        build_existing_recipe_text(recipe),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=add_recipe_keyboard(int(recipe_id)),
    )
    return True
