import logging
import re

from telegram import Update

from bot.app.core.data_models import RecipesStateData
from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import build_recipes_list_keyboard, home_keyboard
from bot.app.services.recipe_service import RecipeService
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db_and_redis
from bot.app.utils.message_utils import collapse_or_edit_recipes_list, safe_edit_message
from packages.common_settings.settings import settings
from packages.redis.repository import RecipeActionCacheRepository

# Включаем логирование
logger = logging.getLogger(__name__)

# допустимые callback_data:
# 'next_3' / 'prev_0'
# 'next_3:breakfast:show' / 'prev_1:search:search'
_PAGE_RE = re.compile(r"^(next|prev)_(\d+)(?:\:([a-z0-9][a-z0-9_-]*)\:(show|search))?$")


async def handler_pagination(update: Update, context: PTBContext) -> None:
    """
    Обрабатывает нажатия кнопок пагинации.
    Entry-point: r"^(next|prev)_\\d+$")
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.data:
        return

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        return
    m = _PAGE_RE.match(cq.data or "")
    if not m:
        # незнакомый callback — просто игнор
        return

    _, page_str, callback_category_slug, callback_mode = m.groups()
    try:
        page = int(page_str)
    except ValueError:
        page = 0

    db, redis = get_db_and_redis(context)
    state_data = await RecipeActionCacheRepository.get(redis, user_id, "recipes_state")
    if not state_data:
        return
    state = RecipesStateData.from_dict(state_data)
    category_slug = callback_category_slug or state.category_slug
    mode_raw = callback_mode or state.mode

    items = state.search_items
    if not items:
        category_id = state.category_id
        if category_id > 0:
            recipe_service = RecipeService(db, redis)
            items = await recipe_service.get_all_recipes_ids_and_titles(user_id, category_id)
    if not items:
        if cq.message:
            await safe_edit_message(cq, "Список рецептов пуст.", reply_markup=home_keyboard())
        return

    per_page = settings.telegram.recipes_per_page
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, max(0, total_pages - 1)))
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

    categories_callback = "recipes_book" if str(category_slug).startswith("book_") else None
    logger.debug("Пагинация рецептов: page=%s category_slug=%s", updated_state.recipes_page, category_slug)
    markup = build_recipes_list_keyboard(
        items,
        page=page,
        per_page=per_page,
        category_slug=category_slug,
        mode=mode,
        categories_callback=categories_callback,
    )
    title = updated_state.display_title

    if cq.message:
        await collapse_or_edit_recipes_list(
            update=update,
            context=context,
            cq=cq,
            redis=redis,
            user_id=user_id,
            title=title,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
