from __future__ import annotations

from contextlib import suppress

from telegram import Message, Update
from telegram.error import BadRequest

from bot.app.core.types import AppState, PTBContext
from packages.redis.repository import RecipeMessageCacheRepository


async def append_message_id_to_cache(source: Update | Message, context: PTBContext, message_id: int) -> None:
    """Добавляет message_id в кэш сообщений пользователя."""
    app_state = context.bot_data.get("state")
    chat_id = None
    user_id = None
    if isinstance(source, Update):
        chat_id = source.effective_chat.id if source.effective_chat else None
        user_id = source.effective_user.id if source.effective_user else None
    elif isinstance(source, Message):
        chat_id = source.chat_id
        user_id = source.from_user.id if source.from_user else None
    if isinstance(app_state, AppState) and app_state.redis is not None and chat_id is not None and user_id is not None:
        await RecipeMessageCacheRepository.append_user_message_ids(
            app_state.redis,
            user_id,
            chat_id,
            [message_id],
        )


async def collapse_user_messages(
    context: PTBContext,
    redis,
    user_id: int,
    current_chat_id: int,
    text: str,
    keyboard,
    *,
    disable_web_page_preview: bool = False,
) -> bool:
    """Удаляет все сохранённые сообщения пользователя, кроме последнего, и редактирует его."""
    data = await RecipeMessageCacheRepository.get_user_message_ids(redis, user_id)
    if not data:
        return False
    chat_id = data.get("chat_id")
    message_ids = data.get("message_ids")
    if not isinstance(chat_id, int) or chat_id != int(current_chat_id):
        await RecipeMessageCacheRepository.clear_user_message_ids(redis, user_id)
        return False
    if not isinstance(message_ids, list) or not message_ids:
        await RecipeMessageCacheRepository.clear_user_message_ids(redis, user_id)
        return False
    for message_id in message_ids[:-1]:
        if not isinstance(message_id, int):
            continue
        with suppress(BadRequest):
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    last_message_id = message_ids[-1]
    if not isinstance(last_message_id, int):
        await RecipeMessageCacheRepository.clear_user_message_ids(redis, user_id)
        return False
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=last_message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=disable_web_page_preview,
        )
    except BadRequest:
        return False
    await RecipeMessageCacheRepository.set_user_message_ids(redis, user_id, chat_id, [last_message_id])
    return True


async def delete_all_user_messages(context: PTBContext, redis, user_id: int, current_chat_id: int) -> None:
    """Удаляет все сохранённые сообщения пользователя в текущем чате."""
    data = await RecipeMessageCacheRepository.get_user_message_ids(redis, user_id)
    if not data:
        return
    chat_id = data.get("chat_id")
    message_ids = data.get("message_ids")
    if not isinstance(chat_id, int) or chat_id != int(current_chat_id):
        await RecipeMessageCacheRepository.clear_user_message_ids(redis, user_id)
        return
    if not isinstance(message_ids, list) or not message_ids:
        await RecipeMessageCacheRepository.clear_user_message_ids(redis, user_id)
        return
    for message_id in message_ids:
        if not isinstance(message_id, int):
            continue
        with suppress(BadRequest):
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    await RecipeMessageCacheRepository.clear_user_message_ids(redis, user_id)
