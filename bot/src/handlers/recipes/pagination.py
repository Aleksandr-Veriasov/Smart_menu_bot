import logging

from aiogram import Bot, Router
from aiogram.types import CallbackQuery
from redis.asyncio import Redis

from bot.src.core.book_slug import is_book_slug
from bot.src.core.data_models import RecipesStateData
from bot.src.core.recipes_mode import RecipeMode
from bot.src.keyboards.callback_data import BookCB, PageCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import recipes_list_keyboard
from bot.src.utils.messaging import collapse_or_edit, safe_edit
from packages.common_settings.settings import settings
from packages.redis.repository import RecipeActionCacheRepository
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="pagination")


@router.callback_query(PageCB.filter())
async def handler_pagination(
    callback: CallbackQuery,
    callback_data: PageCB,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Перелистывание страниц списка рецептов."""
    await callback.answer()
    if not callback.from_user:
        return
    user_id = callback.from_user.id

    state_data = await RecipeActionCacheRepository.get(redis, user_id, "recipes_state")
    if not state_data:
        return
    state = RecipesStateData.from_dict(state_data)
    category_slug = callback_data.category or state.category_slug
    mode_raw = callback_data.mode or state.mode

    items = state.search_items
    if not items and state.category_id > 0:
        items = await recipe_service.get_all_recipes_ids_and_titles(user_id, state.category_id)
    if not items:
        await safe_edit(callback.message, "Список рецептов пуст.", reply_markup=home_keyboard())
        return

    per_page = settings.telegram.recipes_per_page
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(callback_data.page, total_pages - 1))
    try:
        mode = RecipeMode(mode_raw)
    except ValueError:
        mode = RecipeMode.SHOW

    updated_state = state.with_pagination(
        page=page,
        total_pages=total_pages,
        category_slug=category_slug,
        mode=mode,
    )
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", updated_state.to_dict())

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

    await collapse_or_edit(
        callback.message,
        bot,
        redis,
        user_id=user_id,
        title=updated_state.display_title,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
