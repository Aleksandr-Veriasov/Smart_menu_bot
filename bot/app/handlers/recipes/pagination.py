import logging
import re
from contextlib import suppress

from telegram import Update
from telegram.error import BadRequest

from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import build_recipes_list_keyboard, home_keyboard
from bot.app.utils.context_helpers import get_redis_cli
from bot.app.utils.message_cache import collapse_user_messages
from packages.common_settings.settings import settings
from packages.redis.repository import RecipeActionCacheRepository, RecipeCacheRepository

# Включаем логирование
logger = logging.getLogger(__name__)

# допустимые callback_data: 'next_3' / 'prev_0'
_PAGE_RE = re.compile(r"^(next|prev)_(\d+)$")


async def handler_pagination(update: Update, context: PTBContext) -> None:
    """
    Обрабатывает нажатия кнопок пагинации.
    Entry-point: r"^(next|prev)_\\d+$")
    """
    cq = update.callback_query
    if not cq:
        return
    await cq.answer()

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        return
    redis = get_redis_cli(context)
    state = await RecipeActionCacheRepository.get(redis, user_id, "recipes_state")
    if not state:
        return

    items = state.get("search_items")
    if not items:
        category_id = state.get("category_id", 0)
        items = await RecipeCacheRepository.get_all_recipes_ids_and_titles(redis, user_id, category_id)
    if not items:
        if cq.message:
            with suppress(BadRequest):
                await cq.edit_message_text("Список рецептов пуст.", reply_markup=home_keyboard())
        return

    m = _PAGE_RE.match(cq.data or "")
    if not m:
        # незнакомый callback — просто игнор
        return

    _, page_str = m.groups()
    try:
        page = int(page_str)
    except ValueError:
        page = 0

    per_page = settings.telegram.recipes_per_page
    total_pages = int(state.get("recipes_total_pages", 1))
    page = max(0, min(page, max(0, total_pages - 1)))
    mode_raw = state.get("mode", RecipeMode.SHOW.value)
    try:
        mode = RecipeMode(mode_raw)
    except Exception:
        mode = RecipeMode.SHOW
    state["recipes_page"] = page
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state)
    category_slug = state.get("category_slug", "recipes")
    logger.debug("🗑 %s - category_slug", state["recipes_page"])
    markup = build_recipes_list_keyboard(
        items,
        page=page,
        per_page=per_page,
        category_slug=category_slug,
        mode=mode,
    )
    list_title = state.get("list_title")
    if list_title:
        title = list_title
    else:
        title = f'Выберите рецепт из категории «{state.get("category_name", "категория")}»:'

    if cq.message:
        if update.effective_chat:
            if await collapse_user_messages(
                context,
                redis,
                user_id,
                update.effective_chat.id,
                title,
                markup,
                disable_web_page_preview=True,
            ):
                return
        try:
            await cq.edit_message_text(
                title,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
            )
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                with suppress(BadRequest):
                    await cq.edit_message_reply_markup(reply_markup=markup)
            else:
                raise
