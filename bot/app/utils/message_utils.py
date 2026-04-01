import logging
from contextlib import suppress

from redis.asyncio import Redis
from telegram import (
    CallbackQuery,
    InlineKeyboardMarkup,
    MaybeInaccessibleMessage,
    Message,
    Update,
)
from telegram.error import BadRequest

from bot.app.core.types import PTBContext
from bot.app.utils.message_cache import collapse_user_messages
from packages.db.models import Recipe
from packages.redis.repository import UserMessageIdsCacheRepository

# Включаем логирование
logger = logging.getLogger(__name__)


async def safe_edit_message(
    cq: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
) -> None:
    """Безопасно редактирует сообщение и отдельно обрабатывает 'message is not modified'."""
    try:
        await cq.edit_message_text(
            text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            with suppress(BadRequest):
                await cq.edit_message_reply_markup(reply_markup=reply_markup)
                logger.error("Текст сообщения не изменился, обновлено только reply_markup. Подробности: %s", e)
        else:
            logger.error("Ошибка при редактировании сообщения: %s", e)
            raise


async def collapse_or_edit_recipes_list(
    *,
    update: Update,
    context: PTBContext,
    cq: CallbackQuery,
    redis,
    user_id: int,
    title: str,
    reply_markup: InlineKeyboardMarkup,
    disable_web_page_preview: bool = False,
) -> None:
    """Пытается схлопнуть историю сообщений пользователя, иначе редактирует текущее сообщение."""
    if update.effective_chat:
        collapsed = await collapse_user_messages(
            context,
            redis,
            user_id,
            update.effective_chat.id,
            title,
            reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        if collapsed:
            return
    await safe_edit_message(
        cq,
        title,
        reply_markup,
        parse_mode="HTML",
        disable_web_page_preview=disable_web_page_preview,
    )


async def delete_previous_random_video(
    *,
    context: PTBContext,
    redis: Redis,
    user_id: int,
    chat_id: int,
) -> None:
    """Удаляет предыдущее видео случайного рецепта как минимальный message_id из кеша."""
    data = await UserMessageIdsCacheRepository.get_user_message_ids(redis, user_id)
    if not data:
        return
    cached_chat_id = data.get("chat_id")
    message_ids = data.get("message_ids")
    if not isinstance(cached_chat_id, int) or cached_chat_id != int(chat_id):
        return
    if not isinstance(message_ids, list):
        return
    valid_ids = [mid for mid in message_ids if isinstance(mid, int)]
    if len(valid_ids) <= 1:
        return
    previous_video_id = min(valid_ids)
    await delete_message_by_id_safely(context, chat_id=chat_id, message_id=previous_video_id)


async def delete_message_by_id_safely(context: PTBContext, *, chat_id: int, message_id: int) -> None:
    """Удаляет сообщение по chat_id/message_id, игнорируя BadRequest."""
    with suppress(BadRequest):
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)


async def delete_messages(context: PTBContext, *, chat_id: int, message_ids: list[int]) -> None:
    """Удаляет список сообщений в чате, игнорируя BadRequest."""
    for message_id in message_ids:
        if not message_id:
            continue
        await delete_message_by_id_safely(context, chat_id=chat_id, message_id=int(message_id))


async def delete_message_safely(message: Message | MaybeInaccessibleMessage | None) -> None:
    """Удаляет сообщение, если оно существует, игнорируя BadRequest."""
    if not message:
        return
    if isinstance(message, Message):
        with suppress(BadRequest):
            await message.delete()
        return
    bot = getattr(message, "get_bot", lambda: None)()
    chat = getattr(message, "chat", None)
    message_id = getattr(message, "message_id", None)
    chat_id = getattr(chat, "id", None)
    if bot is not None and chat_id is not None and message_id is not None:
        with suppress(BadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=message_id)


def build_existing_recipe_text(recipe: Recipe) -> str:
    """Формирует текст карточки рецепта."""
    ingredients_text = "\n".join(f"- {ingredient.name}" for ingredient in recipe.ingredients)
    return (
        f"🍽 <b>Название рецепта:</b> {recipe.title}\n\n"
        f"📝 <b>Рецепт:</b>\n{recipe.description}\n\n"
        f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
    )
