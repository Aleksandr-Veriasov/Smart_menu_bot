import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.src.bot_ui.messages import MessageService
from bot.src.keyboards.callback_data import RecipeCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import choice_recipe_keyboard, share_recipe_keyboard
from bot.src.recipe_flow.book_slug import is_book_slug
from bot.src.recipe_flow.list_state import RecipesStateData
from bot.src.recipe_flow.modes import RecipeMode
from bot.src.utils.recipe_text import build_existing_recipe_text
from bot.src.utils.share_token import encrypt_recipe_id
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="share_link")


async def build_recipe_share_link(bot: Bot, recipe_id: int | str) -> str:
    """
    Собирает deep-link для шаринга рецепта через параметр start.
    Пример: https://t.me/<bot>?start=share_<token>
    """
    recipe_id_str = str(recipe_id).strip()
    if not recipe_id_str:
        logger.error("Пустой recipe_id при формировании ссылки для шаринга")
        raise ValueError("recipe_id пустой")

    token = encrypt_recipe_id(recipe_id_str)
    payload = f"share_{token}"

    me = await bot.get_me()
    username = me.username or ""
    if not username:
        raise RuntimeError("Username бота пустой")

    url = f"https://t.me/{username.lstrip('@')}?start={payload}"
    logger.info("Сформирована ссылка для шаринга рецепта: %s", url)
    return url


@router.callback_query(RecipeCB.filter(F.action == "share"))
async def share_recipe_link_handler(
    callback: CallbackQuery,
    callback_data: RecipeCB,
    user: User,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
) -> None:
    """Нажатие кнопки «Поделиться рецептом»."""
    await callback.answer()
    recipe_id = callback_data.recipe_id

    url = await build_recipe_share_link(bot, recipe_id)
    recipe = await recipe_service.get_recipe_basic(int(recipe_id))
    title_html = escape(recipe.title) if recipe and recipe.title else "Рецепт"
    desc_html = "—"
    if recipe and recipe.description:
        desc_raw = recipe.description.strip()
        if len(desc_raw) > 150:
            desc_raw = f"{desc_raw[:147]}..."
        desc_html = escape(desc_raw) if desc_raw else "—"

    if not isinstance(callback.message, Message):
        return
    await message_service.delete_tracked_messages(bot, chat_id=callback.message.chat.id)
    await message_service.answer_and_track(
        callback.message,
        f"🍽 <b>Название рецепта:</b> {title_html}\n\n" f"📝 <b>Рецепт:</b>\n{desc_html}\n\n" f"Весь рецепт: {url}",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=share_recipe_keyboard(recipe_id),
    )


@router.callback_query(RecipeCB.filter(F.action == "shareback"))
async def share_recipe_back_handler(
    callback: CallbackQuery,
    callback_data: RecipeCB,
    user: User,
    state: FSMContext,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
) -> None:
    """Возврат из шаринга к карточке рецепта."""
    await callback.answer()
    recipe_id = callback_data.recipe_id
    if not isinstance(callback.message, Message):
        return
    message = callback.message

    await message_service.delete_tracked_messages(bot, chat_id=message.chat.id)

    data = await state.get_data()
    recipes_state = RecipesStateData.from_dict(data.get("recipes_state"))
    category_slug = recipes_state.category_slug
    mode_value = RecipeMode.SHOW.value if recipes_state.mode == RecipeMode.SEARCH.value else recipes_state.mode

    keyboard = choice_recipe_keyboard(
        recipe_id,
        recipes_state.recipes_page,
        category_slug,
        mode_value,
        add_to_self=is_book_slug(category_slug),
        can_manage=mode_value == RecipeMode.SHOW.value and not is_book_slug(category_slug),
    )

    recipe = await recipe_service.get_recipe_for_view(recipe_id)
    if not recipe:
        await message_service.answer_and_track(message, "❌ Рецепт не найден.", reply_markup=home_keyboard())
        return

    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        await message_service.answer_video_and_track(message, video_url)
    await message_service.answer_and_track(
        message,
        build_existing_recipe_text(recipe),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )
