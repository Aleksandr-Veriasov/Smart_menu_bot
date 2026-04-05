import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
)

from bot.app.core.recipes_state import DeleteRecipeState
from bot.app.core.types import PTBContext
from bot.app.handlers.user import user_start
from bot.app.keyboards.callbacks import NavCallbacks, RecipeCallbacks
from bot.app.keyboards.inlines import (
    home_keyboard,
    keyboard_delete,
)
from bot.app.services.recipe_service import RecipeService
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db_and_redis, get_redis_cli
from bot.app.utils.message_cache import (
    delete_all_user_messages,
    send_message_and_cache,
)
from bot.app.utils.message_utils import delete_message_safely, safe_edit_message
from packages.db.repository import RecipeRepository
from packages.redis.repository import (
    RecipeActionCacheRepository,
)

logger = logging.getLogger(__name__)


async def delete_recipe(update: Update, context: PTBContext) -> int:
    """Entry-point: callback `recipe:delete:<recipe_id>`."""
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.data:
        return ConversationHandler.END

    recipe_id = RecipeCallbacks.parse_recipe_delete(cq.data)
    if recipe_id is None:
        await safe_edit_message(cq, "Не смог понять ID рецепта.", reply_markup=home_keyboard())
        logger.error("Ошибка при извлечении recipe_id из callback_data: %s", cq.data)
        return ConversationHandler.END

    db, redis = get_db_and_redis(context)
    async with db.session() as session:
        recipe_name = await RecipeRepository.get_name_by_id(session, recipe_id)
    if not recipe_name:
        await safe_edit_message(cq, "Рецепт не найден.", reply_markup=home_keyboard())
        logger.warning("Рецепт recipe_id=%s не найден в delete_recipe", recipe_id)
        return ConversationHandler.END

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в delete_recipe")
        return ConversationHandler.END

    await RecipeActionCacheRepository.set(redis, user_id, "delete", {"recipe_id": recipe_id})
    await safe_edit_message(
        cq,
        f"Вы точно хотите удалить рецепт <b>{recipe_name}</b>?",
        reply_markup=keyboard_delete(),
        parse_mode=ParseMode.HTML,
    )
    return DeleteRecipeState.CONFIRM_DELETE


async def confirm_delete(update: Update, context: PTBContext) -> int:
    """Подтверждение удаления рецепта."""
    cq = await get_answered_callback_query(update)
    if not cq:
        return ConversationHandler.END
    recipe_id = None

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в confirm_delete")
        return ConversationHandler.END

    db, redis = get_db_and_redis(context)
    delete_data = await RecipeActionCacheRepository.get(redis, user_id, "delete")
    if delete_data and "recipe_id" in delete_data:
        recipe_id = delete_data["recipe_id"]

    if not recipe_id:
        await safe_edit_message(cq, "Не смог понять ID рецепта.", reply_markup=home_keyboard())
        logger.error("Ошибка при извлечении recipe_id из кэша в confirm_delete для user_id=%s", user_id)
        return ConversationHandler.END

    service = RecipeService(db, redis)
    await service.delete_recipe(user_id, recipe_id)

    if cq.message and update.effective_chat:
        chat_id = update.effective_chat.id
        if redis is not None:
            await delete_all_user_messages(context, redis, cq.from_user.id, chat_id)
        else:
            await delete_message_safely(cq.message)
        await send_message_and_cache(
            chat_id=chat_id,
            source=update,
            text="✅ Рецепт успешно удалён.",
            context=context,
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
    else:
        await safe_edit_message(
            cq,
            "✅ Рецепт успешно удалён.",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
    await RecipeActionCacheRepository.delete(redis, user_id, "delete")
    return ConversationHandler.END


async def cancel(update: Update, context: PTBContext) -> int:
    """Отмена редактирования рецепта."""
    msg = update.effective_message
    cq = await get_answered_callback_query(update)
    if cq:
        await safe_edit_message(cq, "Отменено.", reply_markup=home_keyboard())
    elif msg:
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
            CallbackQueryHandler(delete_recipe, pattern=RecipeCallbacks.pattern_recipe_delete()),
        ],
        states={
            DeleteRecipeState.CONFIRM_DELETE: [
                CallbackQueryHandler(confirm_delete, pattern=NavCallbacks.pattern_delete()),
                CallbackQueryHandler(cancel, pattern=NavCallbacks.pattern_cancel()),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=NavCallbacks.pattern_cancel()),
            CallbackQueryHandler(user_start, pattern=NavCallbacks.pattern_start()),
        ],
        per_chat=True,
        per_user=True,
        name="delete_recipe_conversation",
        persistent=True,
    )
