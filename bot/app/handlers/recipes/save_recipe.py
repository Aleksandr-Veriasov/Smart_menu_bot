import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, ConversationHandler

from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.recipes_state import SaveRecipeState
from bot.app.core.types import PTBContext
from bot.app.handlers.user import user_start
from bot.app.keyboards.inlines import category_keyboard, home_keyboard
from bot.app.services.category_service import CategoryService
from bot.app.services.parse_callback import parse_category
from bot.app.services.save_recipe import link_recipe_to_user_service
from bot.app.utils.context_helpers import get_db_and_redis, get_redis_cli
from packages.redis.repository import (
    CategoryCacheRepository,
    PipelineDraftCacheRepository,
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
    data = cq.data or ""
    try:
        _, pipeline_id_str = data.rsplit(":", 1)
        pipeline_id = int(pipeline_id_str)
    except (ValueError, TypeError):
        logger.error("Не удалось распарсить pipeline_id в start_save_recipe")
        return ConversationHandler.END
    try:
        db, redis = get_db_and_redis(context)
    except RuntimeError as e:
        logger.error("Ошибка при получении Redis/DB в save_recipe: %s", e)
        return ConversationHandler.END
    service = CategoryService(db, redis)
    categories = await service.get_all_category()

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в start_save_recipe")
        return ConversationHandler.END
    entry = await PipelineDraftCacheRepository.get(redis, user_id, pipeline_id) or {}
    title = entry.get("title", "")
    await cq.edit_message_text(
        f"🔖 <b>Выберете категорию для этого рецепта:</b>\n\n" f"🍽 <b>Название рецепта:</b>\n{title}\n\n",
        reply_markup=category_keyboard(categories, RecipeMode.SAVE, pipeline_id=pipeline_id),
        parse_mode=ParseMode.HTML,
    )
    return SaveRecipeState.CHOOSE_CATEGORY


async def save_recipe(update: Update, context: PTBContext) -> int:
    """Обработка нажатия «Сохранить рецепт» — привязка к пользователю и категории."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    data = cq.data or ""
    try:
        category_part, pipeline_id_str = data.rsplit(":", 1)
        pipeline_id = int(pipeline_id_str)
    except (ValueError, TypeError):
        logger.error("Не удалось распарсить pipeline_id в save_recipe")
        return ConversationHandler.END

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в save_recipe")
        return ConversationHandler.END
    try:
        db, redis = get_db_and_redis(context)
    except RuntimeError as e:
        logger.error("Ошибка при получении Redis/DB в save_recipe: %s", e)
        return ConversationHandler.END
    entry = await PipelineDraftCacheRepository.get(redis, user_id, pipeline_id) or {}
    category_slug = parse_category(category_part)
    if not category_slug:
        logger.error("Не удалось получить slug категории в save_recipe")
        return ConversationHandler.END

    recipe_id = entry.get("recipe_id")
    title = entry.get("title", "Не указано")

    if not recipe_id:
        logger.warning("Черновик рецепта не найден в save_recipe (pipeline_id=%s, draft=%s)", pipeline_id, entry)
        await cq.edit_message_text(
            "❗️ Не удалось найти черновик рецепта. Пожалуйста, отправьте ссылку заново.",
            reply_markup=home_keyboard(),
        )
        return ConversationHandler.END

    category_name = ""
    try:
        service = CategoryService(db, redis)
        category_id, category_name = await service.get_id_and_name_by_slug_cached(category_slug)
        async with db.session() as session:
            await link_recipe_to_user_service(
                session,
                recipe_id=int(recipe_id),
                user_id=user_id,
                category_id=category_id,
            )
            await CategoryCacheRepository.invalidate_user_categories(redis, user_id)
            await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(redis, user_id, category_id)
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
    await PipelineDraftCacheRepository.delete(redis, user_id, pipeline_id)
    return ConversationHandler.END


async def cancel_recipe_save(update: Update, context: PTBContext) -> int:
    """Обработка нажатия «Не сохранять рецепт» — просто чистим черновик."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    data = cq.data or ""
    try:
        _, pipeline_id_str = data.rsplit(":", 1)
        pipeline_id = int(pipeline_id_str)
    except (ValueError, TypeError):
        logger.error("Не удалось распарсить pipeline_id в cancel_recipe_save")
        return ConversationHandler.END

    user_id = cq.from_user.id if cq.from_user else None
    if user_id:
        try:
            redis = get_redis_cli(context)
        except RuntimeError as e:
            logger.error("Ошибка при получении Redis в cancel_recipe_save: %s", e)
            return ConversationHandler.END
        await PipelineDraftCacheRepository.delete(redis, user_id, pipeline_id)

    await cq.edit_message_text(
        "Рецепт не сохранен.",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )
    return ConversationHandler.END


def save_recipe_handlers() -> ConversationHandler:
    """Создает ConversationHandler для сохранения рецепта."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_save_recipe, pattern=r"^save_recipe:\d+$"),
            CallbackQueryHandler(cancel_recipe_save, pattern=r"^cancel_save_recipe:\d+$"),
        ],
        states={
            SaveRecipeState.CHOOSE_CATEGORY: [
                CallbackQueryHandler(save_recipe, pattern=r"^[a-z0-9][a-z0-9_-]*_save:\d+$")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_recipe_save, pattern=r"^cancel_save_recipe:\d+$"),
            CallbackQueryHandler(user_start, pattern=r"^start$"),
        ],
        per_chat=True,
        per_user=True,
        per_message=True,
        # conversation_timeout=600,
        # name='save_recipe_conversation',
        # persistent=True
    )
