import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.app.core.data_models import RecipesStateData
from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.recipes_state import SearchRecipeState
from bot.app.core.types import PTBContext
from bot.app.handlers.user import user_start
from bot.app.keyboards.callbacks import NavCallbacks, SearchCallbacks
from bot.app.keyboards.inlines import (
    build_recipes_list_keyboard,
    cancel_keyboard,
    home_keyboard,
    search_recipes_type_keyboard,
)
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db_and_redis, get_redis_cli
from bot.app.utils.message_cache import delete_all_user_messages, reply_text_and_cache
from bot.app.utils.message_utils import safe_edit_message
from packages.common_settings.settings import settings
from packages.db.repository import RecipeRepository
from packages.redis.repository import RecipeActionCacheRepository

logger = logging.getLogger(__name__)


async def start_search(update: Update, context: PTBContext) -> int:
    """Entry-point: запросить тип поиска."""
    cq = await get_answered_callback_query(update)
    if not cq:
        return ConversationHandler.END
    await safe_edit_message(
        cq,
        "Поиск идёт только по вашим сохранённым рецептам.\n\n"
        "Выберите способ поиска:\n"
        "<b>• по названию</b> — ищем совпадения в заголовке рецепта\n"
        "<b>• по ингредиентам</b> — ищем совпадения в списке ингредиентов",
        reply_markup=search_recipes_type_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    return SearchRecipeState.CHOOSE_TYPE


async def choose_search_type(update: Update, context: PTBContext) -> int:
    """Выбор типа поиска и запрос текста."""
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.data:
        return ConversationHandler.END
    if cq.data == SearchCallbacks.build_search_type("title"):
        await safe_edit_message(
            cq,
            "Введите слово из названия рецепта:",
            reply_markup=cancel_keyboard(),
        )
        return SearchRecipeState.WAIT_TITLE
    if cq.data == SearchCallbacks.build_search_type("ingredient"):
        await safe_edit_message(
            cq,
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
        await reply_text_and_cache(msg, context, "Пусто. Введите слово ещё раз.")
        return SearchRecipeState.WAIT_TITLE
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        await reply_text_and_cache(msg, context, "Не удалось определить пользователя.", reply_markup=home_keyboard())
        return ConversationHandler.END

    db, redis = get_db_and_redis(context)

    await delete_all_user_messages(context, redis, user_id, msg.chat_id)

    async with db.session() as session:
        items = await RecipeRepository.search_ids_and_titles_by_title(session, user_id, query)

    if not items:
        await reply_text_and_cache(
            msg,
            context,
            f"Ничего не найдено по названию: <b>{query}</b>",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(items) + recipes_per_page - 1) // recipes_per_page
    state = RecipesStateData.for_search(
        search_type="title",
        query=query,
        recipes_total_pages=recipes_total_pages,
        search_items=items,
    )
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state.to_dict())

    markup = build_recipes_list_keyboard(
        items,
        page=0,
        per_page=recipes_per_page,
        category_slug="search",
        mode=RecipeMode.SEARCH,
    )
    await reply_text_and_cache(
        msg,
        context,
        f"Результаты поиска по названию: <b>{query}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def handle_ingredient_query(update: Update, context: PTBContext) -> int:
    """Обработка запроса поиска по ингредиентам."""
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    query = (msg.text or "").strip()
    if not query:
        await reply_text_and_cache(msg, context, "Пусто. Введите ингредиент ещё раз.")
        return SearchRecipeState.WAIT_INGREDIENT
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        await reply_text_and_cache(msg, context, "Не удалось определить пользователя.", reply_markup=home_keyboard())
        return ConversationHandler.END
    redis = get_redis_cli(context)
    if redis is not None:
        await delete_all_user_messages(context, redis, user_id, msg.chat_id)

    db, redis = get_db_and_redis(context)
    async with db.session() as session:
        items = await RecipeRepository.search_ids_and_titles_by_ingredient(session, user_id, query)

    if not items:
        await reply_text_and_cache(
            msg,
            context,
            f"Ничего не найдено по ингредиенту: <b>{query}</b>",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(items) + recipes_per_page - 1) // recipes_per_page
    state = RecipesStateData.for_search(
        search_type="ingredient",
        query=query,
        recipes_total_pages=recipes_total_pages,
        search_items=items,
    )
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state.to_dict())

    markup = build_recipes_list_keyboard(
        items,
        page=0,
        per_page=recipes_per_page,
        category_slug="search",
        mode=RecipeMode.SEARCH,
    )
    await reply_text_and_cache(
        msg,
        context,
        f"Результаты поиска по ингредиенту: <b>{query}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def cancel_search(update: Update, context: PTBContext) -> int:
    """Отмена поиска."""
    msg = update.effective_message
    cq = await get_answered_callback_query(update)
    if cq:
        await safe_edit_message(cq, "Поиск отменен.", reply_markup=home_keyboard())
    elif msg:
        await msg.edit_text("Поиск отменен.", reply_markup=home_keyboard())
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        redis = get_redis_cli(context)
        await RecipeActionCacheRepository.delete(redis, user_id, "recipes_state")
    return ConversationHandler.END


def search_recipes_conversation() -> ConversationHandler:
    """ConversationHandler для поиска рецептов."""
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_search, pattern=SearchCallbacks.pattern_search_recipes())],
        states={
            SearchRecipeState.CHOOSE_TYPE: [
                CallbackQueryHandler(choose_search_type, pattern=SearchCallbacks.pattern_search_type()),
                CallbackQueryHandler(cancel_search, pattern=NavCallbacks.pattern_cancel()),
            ],
            SearchRecipeState.WAIT_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_title_query),
                CallbackQueryHandler(cancel_search, pattern=NavCallbacks.pattern_cancel()),
            ],
            SearchRecipeState.WAIT_INGREDIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ingredient_query),
                CallbackQueryHandler(cancel_search, pattern=NavCallbacks.pattern_cancel()),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_search, pattern=NavCallbacks.pattern_cancel()),
            CallbackQueryHandler(user_start, pattern=NavCallbacks.pattern_start()),
        ],
        per_chat=True,
        per_user=True,
    )
