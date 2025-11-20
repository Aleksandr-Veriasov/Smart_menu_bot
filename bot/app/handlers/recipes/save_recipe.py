import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, ConversationHandler

from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.recipes_state import SaveRecipeState
from bot.app.core.types import AppState, PTBContext
from bot.app.keyboards.inlines import category_keyboard, home_keyboard
from bot.app.services.category_service import CategoryService
from bot.app.services.ingredients_parser import parse_ingredients
from bot.app.services.parse_callback import parse_category
from bot.app.services.save_recipe import save_recipe_service
from bot.app.utils.context_helpers import get_db
from packages.redis.repository import (
    CategoryCacheRepository,
    RecipeCacheRepository,
)

logger = logging.getLogger(__name__)


async def start_save_recipe(update: Update, context: PTBContext) -> int:
    """
    Обработчик команды 'save_recipe' при нажатия кнопки 'Сохранить рецепт'.
    Отправляет пользователю сообщение с подтверждением рецепта.
    """
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    db = get_db(context)
    app_state = context.bot_data.get("state")
    if not isinstance(app_state, AppState) or app_state.redis is None:
        logger.error("AppState или Redis недоступен в start_save_recipe")
        return ConversationHandler.END
    service = CategoryService(db, app_state.redis)
    categories = await service.get_all_category()

    if context.user_data:
        draft = context.user_data.get("recipe_draft", {})
    title = draft.get("title", "")
    await cq.edit_message_text(
        f"🔖 <b>Выберете категорию для этого рецепта:</b>\n\n"
        f"🍽 <b>Название рецепта:</b>\n{title}\n\n",
        reply_markup=category_keyboard(categories, RecipeMode.SAVE),
        parse_mode=ParseMode.HTML,
    )
    return SaveRecipeState.CHOOSE_CATEGORY


async def save_recipe(update: Update, context: PTBContext) -> int:
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    if context.user_data:
        draft = context.user_data.get("recipe_draft", {})
    category_slug = parse_category(cq.data or "")
    if not category_slug:
        logger.error("Не удалось получить slug категории в save_recipe")
        return ConversationHandler.END

    title = draft.get("title", "Не указано")
    description = draft.get("recipe", "Не указано")
    ingredients = draft.get("ingredients", "Не указано")
    video_url = draft.get("video_file_id", "")
    ingredients_raw = parse_ingredients(ingredients)
    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в save_recipe")
        return ConversationHandler.END

    db = get_db(context)
    app_state = context.bot_data.get("state")
    if not isinstance(app_state, AppState) or app_state.redis is None:
        logger.error("AppState или Redis недоступен в save_recipe")
        return ConversationHandler.END
    category_name = ""
    try:
        service = CategoryService(db, app_state.redis)
        category_id, category_name = (
            await service.get_id_and_name_by_slug_cached(category_slug)
        )
        async with db.session() as session:
            await save_recipe_service(
                session,
                user_id=user_id,
                title=title,
                description=description,
                category_id=category_id,
                ingredients_raw=ingredients_raw,
                video_url=video_url,
            )
            await CategoryCacheRepository.invalidate_user_categories(
                app_state.redis, user_id
            )
            await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(
                app_state.redis, user_id, category_id
            )
    except Exception as e:
        logger.exception("Ошибка при сохранении рецепта: %s", e)
        await cq.edit_message_text(
            "❗️ Произошла ошибка при сохранении рецепта. Попробуйте позже.",
            reply_markup=home_keyboard(),
        )
        return ConversationHandler.END
    await cq.edit_message_text(
        f"✅ Ваш рецепт успешно сохранен!\n\n"
        f"🍽 <b>Название рецепта:</b>\n{title}\n\n"
        f"🔖 <b>Категория:</b> {category_name}",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )
    return ConversationHandler.END


async def cancel_recipe_save(update: Update, context: PTBContext) -> int:
    """Обработка нажатия «Не сохранять рецепт» — просто чистим черновик."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    user_id = cq.from_user.id
    if context.user_data:
        context.user_data.pop(user_id, None)

    await cq.edit_message_text(
        "Рецепт не сохранен.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )
    return ConversationHandler.END


def save_recipe_handlers() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_save_recipe, pattern="^save_recipe$"),
            CallbackQueryHandler(
                cancel_recipe_save, pattern="^cancel_save_recipe$"
            ),
        ],
        states={
            SaveRecipeState.CHOOSE_CATEGORY: [
                CallbackQueryHandler(
                    save_recipe, pattern="^[a-z0-9][a-z0-9_-]*_save$"
                )
            ]
        },
        fallbacks=[
            CallbackQueryHandler(
                cancel_recipe_save, pattern="^cancel_save_recipe$"
            )
        ],
        per_chat=True,
        per_user=True,
        per_message=True,
        # conversation_timeout=600,
        # name='save_recipe_conversation',
        # persistent=True
    )
