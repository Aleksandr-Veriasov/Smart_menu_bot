import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.recipes_state import SearchRecipeState
from bot.app.core.types import PTBContext
from bot.app.handlers.user import user_start
from bot.app.keyboards.inlines import (
    build_recipes_list_keyboard,
    cancel_keyboard,
    home_keyboard,
    search_recipes_type_keyboard,
)
from bot.app.utils.context_helpers import get_db_and_redis, get_redis_cli
from bot.app.utils.message_cache import append_message_id_to_cache
from packages.common_settings.settings import settings
from packages.db.repository import RecipeRepository
from packages.redis.repository import RecipeActionCacheRepository

logger = logging.getLogger(__name__)


async def start_search(update: Update, context: PTBContext) -> int:
    """Entry-point: запросить тип поиска."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    await cq.edit_message_text(
        "Поиск идёт только по вашим сохранённым рецептам.\n\n"
        "Выберите способ поиска:\n"
        "<b>• по названию</b> — ищем совпадения в заголовке рецепта\n"
        "<b>• по ингредиентам</b> — ищем совпадения в списке ингредиентов",
        parse_mode=ParseMode.HTML,
        reply_markup=search_recipes_type_keyboard(),
    )
    return SearchRecipeState.CHOOSE_TYPE


async def choose_search_type(update: Update, context: PTBContext) -> int:
    """Выбор типа поиска и запрос текста."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    data = cq.data or ""
    if data == "search:title":
        await cq.edit_message_text(
            "Введите слово из названия рецепта:",
            reply_markup=cancel_keyboard(),
        )
        return SearchRecipeState.WAIT_TITLE
    if data == "search:ingredient":
        await cq.edit_message_text(
            "Введите ингредиент для поиска:",
            reply_markup=cancel_keyboard(),
        )
        return SearchRecipeState.WAIT_INGREDIENT
    return ConversationHandler.END


async def handle_title_query(update: Update, context: PTBContext) -> int:
    """Обработка запроса поиска по названию."""
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    query = (msg.text or "").strip()
    if not query:
        reply = await msg.reply_text("Пусто. Введите слово ещё раз.")
        await append_message_id_to_cache(update, context, reply.message_id)
        return SearchRecipeState.WAIT_TITLE
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        reply = await msg.reply_text("Не удалось определить пользователя.", reply_markup=home_keyboard())
        await append_message_id_to_cache(update, context, reply.message_id)
        return ConversationHandler.END

    db, redis = get_db_and_redis(context)
    async with db.session() as session:
        items = await RecipeRepository.search_ids_and_titles_by_title(session, user_id, query)

    if not items:
        no_results_msg = await msg.reply_text(
            f"Ничего не найдено по названию: <b>{query}</b>",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        await append_message_id_to_cache(update, context, no_results_msg.message_id)
        return ConversationHandler.END

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(items) + recipes_per_page - 1) // recipes_per_page
    state = {
        "search": {"type": "title", "query": query},
        "search_items": items,
        "recipes_page": 0,
        "recipes_total_pages": recipes_total_pages,
        "category_slug": "search",
        "category_id": 0,
        "mode": RecipeMode.SEARCH.value,
        "list_title": f"Результаты поиска по названию: «{query}»",
    }
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state)

    markup = build_recipes_list_keyboard(
        items,
        page=0,
        per_page=recipes_per_page,
        category_slug="search",
        mode=RecipeMode.SEARCH,
    )
    results_msg = await msg.reply_text(
        f"Результаты поиска по названию: <b>{query}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    await append_message_id_to_cache(update, context, results_msg.message_id)
    return ConversationHandler.END


async def handle_ingredient_query(update: Update, context: PTBContext) -> int:
    """Обработка запроса поиска по ингредиентам."""
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    query = (msg.text or "").strip()
    if not query:
        reply = await msg.reply_text("Пусто. Введите ингредиент ещё раз.")
        await append_message_id_to_cache(update, context, reply.message_id)
        return SearchRecipeState.WAIT_INGREDIENT
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        reply = await msg.reply_text("Не удалось определить пользователя.", reply_markup=home_keyboard())
        await append_message_id_to_cache(update, context, reply.message_id)
        return ConversationHandler.END

    db, redis = get_db_and_redis(context)
    async with db.session() as session:
        items = await RecipeRepository.search_ids_and_titles_by_ingredient(session, user_id, query)

    if not items:
        no_results_msg = await msg.reply_text(
            f"Ничего не найдено по ингредиенту: <b>{query}</b>",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        await append_message_id_to_cache(update, context, no_results_msg.message_id)
        return ConversationHandler.END

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(items) + recipes_per_page - 1) // recipes_per_page
    state = {
        "search": {"type": "ingredient", "query": query},
        "search_items": items,
        "recipes_page": 0,
        "recipes_total_pages": recipes_total_pages,
        "category_slug": "search",
        "category_id": 0,
        "mode": RecipeMode.SEARCH.value,
        "list_title": f"Результаты поиска по ингредиенту: «{query}»",
    }
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state)

    markup = build_recipes_list_keyboard(
        items,
        page=0,
        per_page=recipes_per_page,
        category_slug="search",
        mode=RecipeMode.SEARCH,
    )
    results_msg = await msg.reply_text(
        f"Результаты поиска по ингредиенту: <b>{query}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    await append_message_id_to_cache(update, context, results_msg.message_id)
    return ConversationHandler.END


async def cancel_search(update: Update, context: PTBContext) -> int:
    """Отмена поиска."""
    msg = update.effective_message
    if update.callback_query:
        await update.callback_query.answer()
    if msg:
        await msg.edit_text("Поиск отменен.", reply_markup=home_keyboard())
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        redis = get_redis_cli(context)
        await RecipeActionCacheRepository.delete(redis, user_id, "recipes_state")
    return ConversationHandler.END


def search_recipes_conversation() -> ConversationHandler:
    """ConversationHandler для поиска рецептов."""
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_search, pattern=r"^search_recipes$")],
        states={
            SearchRecipeState.CHOOSE_TYPE: [
                CallbackQueryHandler(choose_search_type, pattern=r"^search:(title|ingredient)$"),
                CallbackQueryHandler(cancel_search, pattern=r"^cancel$"),
            ],
            SearchRecipeState.WAIT_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_title_query),
                CallbackQueryHandler(cancel_search, pattern=r"^cancel$"),
            ],
            SearchRecipeState.WAIT_INGREDIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ingredient_query),
                CallbackQueryHandler(cancel_search, pattern=r"^cancel$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_search, pattern=r"^cancel$"),
            CallbackQueryHandler(user_start, pattern=r"^start$"),
        ],
        per_chat=True,
        per_user=True,
    )
