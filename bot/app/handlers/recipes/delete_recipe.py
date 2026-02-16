import logging
from contextlib import suppress

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
)

from bot.app.core.recipes_state import DeleteRecipeState
from bot.app.core.types import PTBContext
from bot.app.handlers.user import user_start
from bot.app.keyboards.inlines import (
    home_keyboard,
    keyboard_delete,
)
from bot.app.services.recipe_service import RecipeService
from bot.app.utils.context_helpers import get_db_and_redis, get_redis_cli
from bot.app.utils.message_cache import (
    append_message_id_to_cache,
    delete_all_user_messages,
)
from packages.db.repository import RecipeRepository
from packages.redis.repository import (
    RecipeActionCacheRepository,
)

logger = logging.getLogger(__name__)


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
        reply_markup=keyboard_delete(),
    )
    return DeleteRecipeState.CONFIRM_DELETE


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
        await RecipeActionCacheRepository.delete(redis, user_id, "delete")
    return ConversationHandler.END


def conversation_delete_recipe() -> ConversationHandler:
    """ConversationHandler для удаления рецепта."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(delete_recipe, pattern=r"^delete_recipe_\d+$"),
        ],
        states={
            DeleteRecipeState.CONFIRM_DELETE: [
                CallbackQueryHandler(confirm_delete, pattern=r"^delete$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CallbackQueryHandler(user_start, pattern=r"^start$"),
        ],
        per_chat=True,
        per_user=True,
        # per_message=True,
        # conversation_timeout=600,  # 10 минут
        # name='edit_recipe_conv',   # если используешь persistence
        # persistent=True,
    )
