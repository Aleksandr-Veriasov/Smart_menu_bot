import logging
from contextlib import suppress

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.recipes_state import EDRState
from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import (
    category_keyboard,
    home_keyboard,
    keyboard_save_cancel_delete,
)
from bot.app.services.category_service import CategoryService
from bot.app.services.parse_callback import parse_change_category
from bot.app.services.recipe_service import RecipeService
from bot.app.utils.context_helpers import get_db, get_db_and_redis, get_redis_cli
from bot.app.utils.message_cache import (
    append_message_id_to_cache,
    delete_all_user_messages,
)
from packages.db.repository import RecipeRepository
from packages.redis.repository import (
    CategoryCacheRepository,
    RecipeActionCacheRepository,
    RecipeCacheRepository,
)

logger = logging.getLogger(__name__)


async def start_edit(update: Update, context: PTBContext) -> int:
    """Entry-point: колбэк вида edit_recipe_{id}."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    data = cq.data or ""
    # парсим id рецепта
    try:
        recipe_id = int(data.rsplit("_", 1)[1])
    except Exception:
        await cq.edit_message_text("Не смог понять ID рецепта.")
        return ConversationHandler.END
    db = get_db(context)
    async with db.session() as session:
        # проверяем, есть ли рецепт с таким ID
        recipe_name = await RecipeRepository.get_name_by_id(session, recipe_id)

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в start_edit")
        return ConversationHandler.END
    redis = get_redis_cli(context)
    await RecipeActionCacheRepository.set(redis, user_id, "edit", {"recipe_id": recipe_id})
    await cq.edit_message_text(
        f"Вы хотите отредактировать название рецепта <b>{recipe_name}</b>?",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard_save_cancel_delete(func="start_edit"),
    )
    return EDRState.CHOOSE_FIELD


async def choose_field(update: Update, context: PTBContext) -> int:
    """Выбираем, что редактировать."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    if cq.data == "f:title":
        await cq.edit_message_text(
            "Введите новое <b>название</b> рецепта:",
            reply_markup=keyboard_save_cancel_delete(),
            parse_mode=ParseMode.HTML,
        )
        return EDRState.WAIT_TITLE
    # отмена
    return await cancel(update, context)


async def handle_title(update: Update, context: PTBContext) -> int:
    """Поймаем текст — это новое название."""
    msg = update.effective_message
    if msg:
        title = (msg.text or "").strip()
        if not title:
            reply = await msg.reply_text("Пусто. Введите название ещё раз.")
            await append_message_id_to_cache(update, context, reply.message_id)
            return EDRState.WAIT_TITLE
        user_id = msg.from_user.id if msg.from_user else None
        if not user_id:
            logger.error("Не удалось получить user_id в handle_title")
            return ConversationHandler.END
        redis = get_redis_cli(context)
        edit_state = await RecipeActionCacheRepository.get(redis, user_id, "edit") or {}
        edit_state["title"] = title
        await RecipeActionCacheRepository.set(redis, user_id, "edit", edit_state)
        reply = await msg.reply_text(
            f"Сохранить название:\n<b>{title}</b>",
            reply_markup=keyboard_save_cancel_delete(func="handle_title"),
            parse_mode=ParseMode.HTML,
        )
        await append_message_id_to_cache(update, context, reply.message_id)
        return EDRState.CONFIRM_TITLE
    return ConversationHandler.END


async def save_changes(update: Update, context: PTBContext) -> int:
    """Сохраняем в БД и завершаем диалог."""
    msg = update.effective_message
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в save_changes")
        return ConversationHandler.END
    redis = get_redis_cli(context)
    edit = await RecipeActionCacheRepository.get(redis, user_id, "edit") or {}
    recipe_id = int(edit.get("recipe_id", 0))
    title = edit.get("title")

    if not recipe_id or not title:
        if msg:
            reply = await msg.reply_text("Нет изменений для сохранения.")
            await append_message_id_to_cache(update, context, reply.message_id)
        return ConversationHandler.END

    try:
        db, redis = get_db_and_redis(context)
    except RuntimeError as e:
        logger.error("Ошибка при получении Redis/DB в save_recipe: %s", e)
        return ConversationHandler.END
    service = RecipeService(db, redis)
    await service.update_recipe_title(
        user_id=user_id,
        recipe_id=recipe_id,
        new_title=title,
    )
    if msg:
        await msg.edit_text("✅ Изменения сохранены.", reply_markup=home_keyboard())
    await RecipeActionCacheRepository.delete(redis, user_id, "edit")
    return ConversationHandler.END


async def delete_recipe(update: Update, context: PTBContext) -> int:
    """Entry-point: колбэк вида delete_recipe_{id}."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    data = cq.data or ""
    # парсим id рецепта
    try:
        recipe_id = int(data.rsplit("_", 1)[1])
    except Exception:
        await cq.edit_message_text("Не смог понять ID рецепта.")
        return ConversationHandler.END

    db, redis = get_db_and_redis(context)
    async with db.session() as session:
        # проверяем, есть ли рецепт с таким ID
        recipe_name = await RecipeRepository.get_name_by_id(session, recipe_id)

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в delete_recipe")
        return ConversationHandler.END

    await RecipeActionCacheRepository.set(redis, user_id, "delete", {"recipe_id": recipe_id})
    await cq.edit_message_text(
        f"Вы точно хотите удалить рецепт <b>{recipe_name}</b>?",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard_save_cancel_delete(func="delete_recipe"),
    )
    return EDRState.CONFIRM_DELETE


async def confirm_delete(update: Update, context: PTBContext) -> int:
    """Подтверждение удаления рецепта."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    recipe_id = None

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в confirm_delete")
        return ConversationHandler.END

    try:
        db, redis = get_db_and_redis(context)
    except RuntimeError as e:
        logger.error("Ошибка при получении Redis/DB в save_recipe: %s", e)
        return ConversationHandler.END

    delete_data = await RecipeActionCacheRepository.get(redis, user_id, "delete")
    if delete_data and "recipe_id" in delete_data:
        recipe_id = delete_data["recipe_id"]

    if not recipe_id:
        await cq.edit_message_text("Не смог понять ID рецепта.")
        return ConversationHandler.END

    service = RecipeService(db, redis)
    await service.delete_recipe(user_id, recipe_id)

    if cq.message and update.effective_chat:
        chat_id = update.effective_chat.id
        if redis is not None:
            await delete_all_user_messages(context, redis, cq.from_user.id, chat_id)
        with suppress(BadRequest):
            await context.bot.delete_message(chat_id=chat_id, message_id=cq.message.message_id)
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Рецепт успешно удалён.",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        await append_message_id_to_cache(update, context, sent.message_id)
    else:
        await cq.edit_message_text(
            "✅ Рецепт успешно удалён.",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
    await RecipeActionCacheRepository.delete(redis, user_id, "delete")
    return ConversationHandler.END


async def change_category(update: Update, context: PTBContext) -> int:
    """Entry-point: колбэк вида change_category:{id}."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    data = cq.data or ""
    # парсим id рецепта
    try:
        recipe_id = int(data.rsplit(":", 1)[1])
    except Exception:
        await cq.edit_message_text("Не смог понять ID рецепта.")
        return ConversationHandler.END
    try:
        db, redis = get_db_and_redis(context)
    except RuntimeError as e:
        logger.error("Ошибка при получении Redis/DB в save_recipe: %s", e)
        return ConversationHandler.END
    service = CategoryService(db, redis)
    category = await service.get_all_category()
    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в change_category")
        return ConversationHandler.END
    await RecipeActionCacheRepository.set(redis, user_id, "change_category", {"recipe_id": recipe_id})
    await cq.edit_message_text(
        "🏷️ Выберете новую категорию:",
        parse_mode=ParseMode.HTML,
        reply_markup=category_keyboard(
            category,
            RecipeMode.EDIT,
            callback_builder=lambda slug: f"change_category:{slug}",
        ),
    )
    return EDRState.CONFIRM_CHANGE_CATEGORY


async def confirm_change_category(update: Update, context: PTBContext) -> int:
    """Подтверждение изменения категории рецепта."""
    cq = update.callback_query
    if not cq:
        return ConversationHandler.END
    await cq.answer()
    recipe_id = None

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в confirm_change_category")
        return ConversationHandler.END

    try:
        db, redis = get_db_and_redis(context)
    except RuntimeError as e:
        logger.error("Ошибка при получении Redis/DB в save_recipe: %s", e)
        return ConversationHandler.END

    change_category = await RecipeActionCacheRepository.get(redis, user_id, "change_category")
    if change_category and "recipe_id" in change_category:
        recipe_id = change_category["recipe_id"]

    if not recipe_id:
        await cq.edit_message_text("Не смог понять ID рецепта.")
        return ConversationHandler.END
    category_slug = parse_change_category(cq.data or "")
    if not category_slug:
        logger.error("Не удалось получить slug категории в confirm_change_category")
        return ConversationHandler.END

    service = CategoryService(db, redis)
    try:
        category_id, _ = await service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        logger.error("Категория не найдена в confirm_change_category: %s", category_slug)
        await cq.edit_message_text(
            "Категория не найдена. Пожалуйста, выберите другую.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_keyboard(),
        )
        return ConversationHandler.END
    async with db.session() as session:
        recipe_title = await RecipeRepository.update_category(
            session,
            recipe_id,
            cq.from_user.id,
            category_id,
        )
    await CategoryCacheRepository.invalidate_user_categories(redis, cq.from_user.id)
    await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(redis, cq.from_user.id, category_id)
    logger.debug(f"🗑️ Инвалидирован кэш категорий юзера {cq.from_user.id}")
    await cq.edit_message_text(
        f"✅ Категория рецепта <b>{recipe_title}</b> изменена",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )
    await RecipeActionCacheRepository.delete(redis, user_id, "change_category")
    return ConversationHandler.END


async def cancel(update: Update, context: PTBContext) -> int:
    """Отмена редактирования рецепта."""
    # поддержим и колбэк, и команду
    msg = update.effective_message
    if update.callback_query:
        await update.callback_query.answer()
    if msg:
        await msg.edit_text("Отменено.", reply_markup=home_keyboard())
    if msg and msg.from_user:
        redis = get_redis_cli(context)
        user_id = msg.from_user.id
        await RecipeActionCacheRepository.delete(redis, user_id, "edit")
        await RecipeActionCacheRepository.delete(redis, user_id, "delete")
        await RecipeActionCacheRepository.delete(redis, user_id, "change_category")
    return ConversationHandler.END


def conversation_edit_recipe() -> ConversationHandler:
    """ConversationHandler для редактирования и удаления рецепта."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_edit, pattern=r"^edit_recipe_(\d+)$"),
            CallbackQueryHandler(delete_recipe, pattern=r"^delete_recipe_\d+$"),
            CallbackQueryHandler(change_category, pattern=r"^change_category:\d+$"),
        ],
        states={
            EDRState.CHOOSE_FIELD: [
                CallbackQueryHandler(choose_field, pattern=r"^(f:title|f:desc|cancel)$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            EDRState.WAIT_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_title),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            EDRState.CONFIRM_TITLE: [
                CallbackQueryHandler(save_changes, pattern=r"^save_changes$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            EDRState.CONFIRM_DELETE: [
                CallbackQueryHandler(confirm_delete, pattern=r"^delete$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
            EDRState.CONFIRM_CHANGE_CATEGORY: [
                CallbackQueryHandler(
                    confirm_change_category,
                    pattern=r"^change_category:[a-z0-9][a-z0-9_-]*$",
                ),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern=r"^cancel$")],
        per_chat=True,
        per_user=True,
        # per_message=True,
        # conversation_timeout=600,  # 10 минут
        # name='edit_recipe_conv',   # если используешь persistence
        # persistent=True,
    )
