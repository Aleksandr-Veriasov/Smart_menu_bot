from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from telegram import Message, Update
from telegram.error import BadRequest

from bot.app.core.types import PTBContext
from bot.app.utils.context_helpers import get_redis_cli
from packages.redis.repository import UserMessageIds, UserMessageIdsCacheRepository


@dataclass(slots=True)
class CachedMessages:
    """Нормализованный кеш последних сообщений пользователя."""

    chat_id: int
    message_ids: list[int]

    @property
    def last_message_id(self) -> int | None:
        """Возвращает идентификатор последнего сообщения из кеша."""
        return self.message_ids[-1] if self.message_ids else None


def to_cached_messages(data: UserMessageIds | None) -> CachedMessages | None:
    """Преобразует данные репозитория кеша сообщений в типизированную структуру."""
    if data is None:
        return None

    chat_id = data.get("chat_id")
    message_ids = data.get("message_ids")
    if not isinstance(chat_id, int) or not isinstance(message_ids, list) or not message_ids:
        return None
    if not all(isinstance(message_id, int) for message_id in message_ids):
        return None

    return CachedMessages(chat_id=chat_id, message_ids=message_ids)


async def append_message_id_to_cache(
    source: Update | Message,
    context: PTBContext,
    message_id: int,
    *,
    user_id: int | None = None,
) -> None:
    """Добавляет message_id в кэш сообщений пользователя."""
    redis = get_redis_cli(context)
    chat_id = None
    resolved_user_id = user_id
    if isinstance(source, Update):
        chat_id = source.effective_chat.id if source.effective_chat else None
        if resolved_user_id is None:
            resolved_user_id = source.effective_user.id if source.effective_user else None
    elif isinstance(source, Message):
        chat_id = source.chat_id
        if resolved_user_id is None:
            resolved_user_id = source.from_user.id if source.from_user else None
    if redis is not None and chat_id is not None and resolved_user_id is not None:
        await UserMessageIdsCacheRepository.append_user_message_ids(
            redis,
            user_id=resolved_user_id,
            chat_id=chat_id,
            message_ids=[message_id],
        )


async def reply_text_and_cache(
    message: Message,
    context: PTBContext,
    text: str,
    *,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отправляет reply-сообщение и сохраняет его идентификатор в Redis."""
    sent = await message.reply_text(text, **kwargs)
    await append_message_id_to_cache(message, context, sent.message_id, user_id=user_id)
    return sent


async def reply_video_and_cache(
    message: Message,
    context: PTBContext,
    video,
    *,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отправляет reply-видео и сохраняет его идентификатор в Redis."""
    sent = await message.reply_video(video, **kwargs)
    await append_message_id_to_cache(message, context, sent.message_id, user_id=user_id)
    return sent


async def send_message_and_cache(
    source: Update | Message,
    context: PTBContext,
    chat_id: int,
    text: str,
    *,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отправляет сообщение в чат и сохраняет его идентификатор в Redis."""
    sent = await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    await append_message_id_to_cache(source, context, sent.message_id, user_id=user_id)
    return sent


async def send_video_and_cache(
    source: Update | Message,
    context: PTBContext,
    chat_id: int,
    video,
    *,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отправляет видео в чат и сохраняет его идентификатор в Redis."""
    sent = await context.bot.send_video(chat_id=chat_id, video=video, **kwargs)
    await append_message_id_to_cache(source, context, sent.message_id, user_id=user_id)
    return sent


async def collapse_user_messages(
    context: PTBContext,
    redis,
    user_id: int,
    current_chat_id: int,
    text: str,
    keyboard,
    *,
    current_message_id: int | None = None,
    disable_web_page_preview: bool = False,
) -> bool:
    """Удаляет все сохранённые сообщения пользователя, кроме последнего, и редактирует его."""
    data = await UserMessageIdsCacheRepository.get_user_message_ids(redis, user_id)
    cached = to_cached_messages(data)
    if cached is None:
        return False

    if cached.chat_id != int(current_chat_id):
        await UserMessageIdsCacheRepository.clear_user_message_ids(redis, user_id)
        return False

    for message_id in cached.message_ids[:-1]:
        with suppress(BadRequest):
            await context.bot.delete_message(chat_id=cached.chat_id, message_id=message_id)

    last_message_id = cached.last_message_id
    if last_message_id is None:
        return False

    try:
        await context.bot.edit_message_text(
            chat_id=cached.chat_id,
            message_id=last_message_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=disable_web_page_preview,
        )
    except BadRequest:
        return False
    await UserMessageIdsCacheRepository.set_user_message_ids(
        redis,
        user_id=user_id,
        chat_id=cached.chat_id,
        message_ids=[last_message_id],
    )
    if current_message_id is not None and current_message_id != last_message_id:
        with suppress(BadRequest):
            await context.bot.delete_message(chat_id=cached.chat_id, message_id=current_message_id)
    return True


async def delete_all_user_messages(context: PTBContext, redis, user_id: int, current_chat_id: int) -> None:
    """Удаляет все сохранённые сообщения пользователя в текущем чате."""
    data = await UserMessageIdsCacheRepository.get_user_message_ids(redis, user_id)
    cached = to_cached_messages(data)
    if cached is None:
        return

    if cached.chat_id != int(current_chat_id):
        await UserMessageIdsCacheRepository.clear_user_message_ids(redis, user_id)
        return

    for message_id in cached.message_ids:
        with suppress(BadRequest):
            await context.bot.delete_message(chat_id=cached.chat_id, message_id=message_id)
    await UserMessageIdsCacheRepository.clear_user_message_ids(redis, user_id)
