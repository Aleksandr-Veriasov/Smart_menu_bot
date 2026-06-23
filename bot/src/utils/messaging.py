"""Хелперы отправки/трекинга сообщений с явными зависимостями (bot/redis).

Идиоматичная замена прежним `*_and_cache(message, context, ...)`: вместо
god-object `context` функции принимают ровно то, что используют — `redis`
для трекинга и `bot`/`Message` для отправки.

Трекинг message_id нужен, чтобы при следующем экране удалять/схлопывать
предыдущие сообщения пользователя и не засорять чат.
"""

from contextlib import suppress
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message
from redis.asyncio import Redis

from packages.redis.repository import UserMessageIdsCacheRepository


async def track_message(redis: Redis, *, user_id: int | None, chat_id: int | None, message_id: int) -> None:
    """Запоминает message_id пользователя в Redis для последующей очистки."""
    if user_id is None or chat_id is None:
        return
    await UserMessageIdsCacheRepository.append_user_message_ids(
        redis,
        user_id=user_id,
        chat_id=chat_id,
        message_ids=[message_id],
    )


async def answer_and_track(
    message: Message,
    redis: Redis,
    text: str,
    *,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отвечает пользователю и трекает сообщение."""
    sent = await message.answer(text, **kwargs)
    resolved_user_id = user_id if user_id is not None else (message.from_user.id if message.from_user else None)
    await track_message(redis, user_id=resolved_user_id, chat_id=message.chat.id, message_id=sent.message_id)
    return sent


async def answer_video_and_track(
    message: Message,
    redis: Redis,
    video: Any,
    *,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отправляет видео пользователю и трекает сообщение."""
    sent = await message.answer_video(video, **kwargs)
    resolved_user_id = user_id if user_id is not None else (message.from_user.id if message.from_user else None)
    await track_message(redis, user_id=resolved_user_id, chat_id=message.chat.id, message_id=sent.message_id)
    return sent


async def send_and_track(
    bot: Bot,
    redis: Redis,
    *,
    chat_id: int,
    text: str,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отправляет сообщение в чат и трекает его."""
    sent = await bot.send_message(chat_id, text, **kwargs)
    await track_message(redis, user_id=user_id, chat_id=chat_id, message_id=sent.message_id)
    return sent


async def send_video_and_track(
    bot: Bot,
    redis: Redis,
    *,
    chat_id: int,
    video: Any,
    user_id: int | None = None,
    **kwargs: Any,
) -> Message:
    """Отправляет видео в чат и трекает его."""
    sent = await bot.send_video(chat_id, video, **kwargs)
    await track_message(redis, user_id=user_id, chat_id=chat_id, message_id=sent.message_id)
    return sent


async def delete_message_safely(message: Message | None) -> None:
    """Удаляет сообщение, если оно доступно, игнорируя ошибки Telegram."""
    if not isinstance(message, Message):
        return
    with suppress(TelegramBadRequest):
        await message.delete()


async def delete_messages(bot: Bot, *, chat_id: int, message_ids: list[int]) -> None:
    """Удаляет перечисленные сообщения, игнорируя ошибки Telegram."""
    for message_id in message_ids:
        if not message_id:
            continue
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=int(message_id))


async def delete_tracked_messages(bot: Bot, redis: Redis, *, user_id: int, chat_id: int) -> None:
    """Удаляет все ранее затреканные сообщения пользователя в текущем чате."""
    data = await UserMessageIdsCacheRepository.get_user_message_ids(redis, user_id)
    if not data:
        return

    cached_chat_id = data.get("chat_id")
    message_ids = data.get("message_ids")
    if not isinstance(cached_chat_id, int) or not isinstance(message_ids, list):
        await UserMessageIdsCacheRepository.clear_user_message_ids(redis, user_id)
        return
    if cached_chat_id != int(chat_id):
        await UserMessageIdsCacheRepository.clear_user_message_ids(redis, user_id)
        return

    for message_id in message_ids:
        if not isinstance(message_id, int):
            continue
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=cached_chat_id, message_id=message_id)
    await UserMessageIdsCacheRepository.clear_user_message_ids(redis, user_id)


async def safe_edit(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
) -> None:
    """Безопасно редактирует сообщение, гася ошибку «message is not modified»."""
    if not isinstance(message, Message):
        return
    try:
        await message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
        with suppress(TelegramBadRequest):
            await message.edit_reply_markup(reply_markup=reply_markup)


async def collapse_user_messages(
    bot: Bot,
    redis: Redis,
    *,
    user_id: int,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    disable_web_page_preview: bool = False,
) -> bool:
    """Удаляет все затреканные сообщения пользователя, кроме последнего, и редактирует его.

    Возвращает True, если получилось схлопнуть историю в одно отредактированное
    сообщение, иначе False (вызывающий код тогда редактирует текущее сообщение).
    """
    data = await UserMessageIdsCacheRepository.get_user_message_ids(redis, user_id)
    chat = data.get("chat_id") if data else None
    message_ids = data.get("message_ids") if data else None
    if not isinstance(chat, int) or not isinstance(message_ids, list) or not message_ids:
        return False
    if not all(isinstance(mid, int) for mid in message_ids):
        return False
    if chat != int(chat_id):
        await UserMessageIdsCacheRepository.clear_user_message_ids(redis, user_id)
        return False

    for message_id in message_ids[:-1]:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat, message_id=message_id)

    last_message_id = message_ids[-1]
    try:
        await bot.edit_message_text(
            chat_id=chat,
            message_id=last_message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest:
        return False

    await UserMessageIdsCacheRepository.set_user_message_ids(
        redis,
        user_id=user_id,
        chat_id=chat,
        message_ids=[last_message_id],
    )
    return True


async def collapse_or_edit(
    message: Message,
    bot: Bot,
    redis: Redis,
    *,
    user_id: int,
    title: str,
    reply_markup: InlineKeyboardMarkup | None,
    disable_web_page_preview: bool = False,
) -> None:
    """Пытается схлопнуть историю сообщений, иначе редактирует текущее сообщение."""
    if isinstance(message, Message):
        collapsed = await collapse_user_messages(
            bot,
            redis,
            user_id=user_id,
            chat_id=message.chat.id,
            text=title,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        if collapsed:
            return
    await safe_edit(
        message,
        title,
        reply_markup=reply_markup,
        parse_mode="HTML",
        disable_web_page_preview=disable_web_page_preview,
    )


async def delete_previous_random_video(bot: Bot, redis: Redis, *, user_id: int, chat_id: int) -> None:
    """Удаляет предыдущее видео случайного рецепта (минимальный message_id из кеша)."""
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
    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id=chat_id, message_id=min(valid_ids))
