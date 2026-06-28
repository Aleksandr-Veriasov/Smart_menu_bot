from contextlib import suppress
from typing import Any

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from bot.src.bot_ui.message_ids import MessageIdsStore


class MessageService:
    """Сервис Telegram UI-сообщений с трекингом отправленных message_id."""

    def __init__(self, message_ids_store: MessageIdsStore) -> None:
        """Создаёт сервис поверх хранилища UI message_id."""
        self.message_ids_store = message_ids_store

    async def safe_edit(
        self,
        message: Message,
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: ParseMode | str | None = None,
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

    async def delete_message_safely(self, message: Message | None) -> None:
        """Удаляет сообщение, если оно доступно, игнорируя ошибки Telegram."""
        if not isinstance(message, Message):
            return
        with suppress(TelegramBadRequest):
            await message.delete()

    async def delete_messages(self, bot: Bot, *, chat_id: int, message_ids: list[int]) -> None:
        """Удаляет перечисленные сообщения, игнорируя ошибки Telegram."""
        for message_id in message_ids:
            if not message_id:
                continue
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=int(message_id))

    async def track_message(self, *, chat_id: int | None, message_id: int) -> None:
        """Запоминает message_id пользователя для последующей очистки."""
        if chat_id is None:
            return
        await self.message_ids_store.append(
            chat_id=chat_id,
            message_ids=[message_id],
        )

    async def answer_and_track(
        self,
        message: Message,
        text: str,
        **kwargs: Any,
    ) -> Message:
        """Отвечает на входящее сообщение и сохраняет sent message_id в UI-трекинг."""
        sent = await message.answer(text, **kwargs)
        await self.track_message(chat_id=message.chat.id, message_id=sent.message_id)
        return sent

    async def answer_video_and_track(
        self,
        message: Message,
        video: Any,
        **kwargs: Any,
    ) -> Message:
        """Отправляет видео ответом на сообщение и сохраняет sent message_id в UI-трекинг."""
        sent = await message.answer_video(video, **kwargs)
        await self.track_message(chat_id=message.chat.id, message_id=sent.message_id)
        return sent

    async def send_and_track(
        self,
        bot: Bot,
        *,
        chat_id: int,
        text: str,
        **kwargs: Any,
    ) -> Message:
        """Отправляет текстовое сообщение в чат и сохраняет sent message_id в UI-трекинг."""
        sent = await bot.send_message(chat_id, text, **kwargs)
        await self.track_message(chat_id=chat_id, message_id=sent.message_id)
        return sent

    async def send_video_and_track(
        self,
        bot: Bot,
        *,
        chat_id: int,
        video: Any,
        **kwargs: Any,
    ) -> Message:
        """Отправляет видео в чат и сохраняет sent message_id в UI-трекинг."""
        sent = await bot.send_video(chat_id, video, **kwargs)
        await self.track_message(chat_id=chat_id, message_id=sent.message_id)
        return sent

    async def delete_tracked_messages(self, bot: Bot, *, chat_id: int) -> None:
        """Удаляет все затреканные сообщения пользователя в указанном чате и чистит UI-трекинг."""
        data = await self.message_ids_store.get()
        if not data:
            return

        if data.chat_id != int(chat_id):
            await self.message_ids_store.clear()
            return

        for message_id in data.message_ids:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=data.chat_id, message_id=message_id)
        await self.message_ids_store.clear()

    async def delete_previous_random_video(self, bot: Bot, *, chat_id: int) -> None:
        """Удаляет предыдущее видео случайного рецепта, если оно есть в UI-трекинге."""
        data = await self.message_ids_store.get()
        if not data or data.chat_id != int(chat_id):
            return
        if len(data.message_ids) <= 1:
            return
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id=chat_id, message_id=min(data.message_ids))

    async def collapse_or_edit(
        self,
        message: Message,
        bot: Bot,
        *,
        title: str,
        reply_markup: InlineKeyboardMarkup | None,
        disable_web_page_preview: bool = False,
    ) -> None:
        """Схлопывает затреканные сообщения в одно редактированное или редактирует текущее."""
        if isinstance(message, Message):
            collapsed = await self._collapse_user_messages(
                bot,
                chat_id=message.chat.id,
                text=title,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
            if collapsed:
                return
        await self.safe_edit(
            message,
            title,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=disable_web_page_preview,
        )

    async def remember_tracked_messages(self, *, chat_id: int, message_ids: list[int]) -> None:
        """Перезаписывает список message_id, связанных с пользователем и текущим UI-экраном."""
        await self.message_ids_store.set(
            chat_id=chat_id,
            message_ids=message_ids,
        )

    async def _collapse_user_messages(
        self,
        bot: Bot,
        *,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
        disable_web_page_preview: bool = False,
    ) -> bool:
        """Удаляет все затреканные сообщения, кроме последнего, и редактирует последнее."""
        data = await self.message_ids_store.get()
        chat = data.chat_id if data else None
        message_ids = data.message_ids if data else None
        if not isinstance(chat, int) or not isinstance(message_ids, list) or not message_ids:
            return False
        if not all(isinstance(mid, int) for mid in message_ids):
            return False
        if chat != int(chat_id):
            await self.message_ids_store.clear()
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
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=disable_web_page_preview,
            )
        except TelegramBadRequest:
            return False

        await self.message_ids_store.set(
            chat_id=chat,
            message_ids=[last_message_id],
        )
        return True
