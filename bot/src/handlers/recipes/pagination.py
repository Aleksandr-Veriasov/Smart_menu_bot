import logging

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, User

from bot.src.bot_ui.messages import MessageService
from bot.src.keyboards.callback_data import BookCB, PageCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import recipes_list_keyboard
from bot.src.recipe_flow.book_slug import is_book_slug
from bot.src.recipe_flow.list_state import RecipesStateData
from bot.src.recipe_flow.modes import RecipeMode
from packages.common_settings.settings import settings
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="pagination")


@router.callback_query(PageCB.filter())
async def handler_pagination(
    callback: CallbackQuery,
    callback_data: PageCB,
    user: User,
    state: FSMContext,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
) -> None:
    """Перелистывание страниц списка рецептов."""
    await callback.answer()

    data = await state.get_data()
    recipes_state_data = data.get("recipes_state")
    if not recipes_state_data:
        return
    recipes_state = RecipesStateData.from_dict(recipes_state_data)
    category_slug = callback_data.category or recipes_state.category_slug
    mode_raw = callback_data.mode or recipes_state.mode

    items = recipes_state.search_items
    if not items and recipes_state.category_id > 0:
        items = await recipe_service.get_all_by_user_and_category(user.id, recipes_state.category_id)
    if not items:
        await message_service.safe_edit(callback.message, "Список рецептов пуст.", reply_markup=home_keyboard())
        return

    per_page = settings.telegram.recipes_per_page
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(callback_data.page, total_pages - 1))
    try:
        mode = RecipeMode(mode_raw)
    except ValueError:
        mode = RecipeMode.SHOW

    updated_recipes_state = recipes_state.with_pagination(
        page=page,
        total_pages=total_pages,
        category_slug=category_slug,
        mode=mode,
    )
    await state.update_data(recipes_state=updated_recipes_state.to_dict())

    categories_callback = BookCB() if is_book_slug(category_slug) else None
    logger.debug("Пагинация рецептов: page=%s category_slug=%s", page, category_slug)
    markup = recipes_list_keyboard(
        items,
        page=page,
        per_page=per_page,
        category_slug=category_slug,
        mode=mode,
        categories_callback=categories_callback,
    )

    await message_service.collapse_or_edit(
        callback.message,
        bot,
        title=updated_recipes_state.display_title,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
