"""Отправка сообщений в Telegram из media_worker через aiogram Bot."""

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from packages.common_settings.settings import settings
from packages.media.video_converter import async_probe_video_dimensions
from packages.notifications.edit_throttle import EditThrottle
from packages.notifications.formatting import (
    format_error_text,
    format_progress_bar,
    format_recipe_html,
)

logger = logging.getLogger(__name__)


def _save_keyboard(pipeline_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сохранить рецепт", callback_data=f"save:start:{pipeline_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"save:cancel:{pipeline_id}")],
        ]
    )


class MediaWorkerNotifier:
    """Обновляет прогресс-сообщение и отправляет финальную карточку рецепта."""

    def __init__(self, bot_token: str, min_edit_interval: float = 1.0) -> None:
        self._bot = Bot(token=bot_token)
        self._throttle = EditThrottle(min_edit_interval)

    async def close(self) -> None:
        await self._bot.session.close()

    async def edit_progress(self, chat_id: int, message_id: int, pct: int, label: str = "") -> None:
        """Редактировать прогресс-сообщение с троттлингом."""
        await self._throttle.wait_async()
        text = format_progress_bar(pct, label)
        try:
            await self._bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
            self._throttle.mark()
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.warning("edit_progress: %s", e)

    async def send_error(self, chat_id: int, message_id: int | None, text: str) -> None:
        """Поставить ❌ в прогресс-сообщение (или отправить новое, если id нет)."""
        error_text = format_error_text(text)
        try:
            if message_id is not None:
                await self._bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=error_text)
            else:
                await self._bot.send_message(chat_id=chat_id, text=error_text)
        except Exception:
            try:
                await self._bot.send_message(chat_id=chat_id, text=error_text)
            except Exception:
                logger.exception("send_error failed")

    async def send_recipe_card(
        self,
        chat_id: int,
        *,
        title: str,
        recipe: str,
        ingredients: list[str] | str,
        pipeline_id: int,
    ) -> int | None:
        """Отправить карточку рецепта с кнопками «Сохранить / Отмена»."""
        try:
            msg = await self._bot.send_message(
                chat_id=chat_id,
                text=format_recipe_html(title, recipe, ingredients),
                parse_mode="HTML",
                reply_markup=_save_keyboard(pipeline_id),
            )
            return msg.message_id
        except Exception:
            logger.exception("send_recipe_card failed")
            return None

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Удалить сообщение, игнорируя ошибки (уже удалено / недоступно)."""
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramBadRequest as e:
            logger.debug("delete_message: %s", e)
        except Exception:
            logger.exception("delete_message failed (chat_id=%s, message_id=%s)", chat_id, message_id)

    async def send_video_to_user(self, chat_id: int, video_file_id: str) -> int | None:
        """Отправить видео пользователю по file_id. Возвращает message_id или None при ошибке."""
        try:
            msg = await self._bot.send_video(chat_id=chat_id, video=video_file_id, supports_streaming=True)
            return msg.message_id
        except Exception:
            logger.exception("send_video_to_user failed (chat_id=%s)", chat_id)
            return None

    async def upload_video_to_channel(self, video_path: str, *, caption: str = "📹 Новое видео!") -> str:
        """Загрузить видео в канал. Возвращает file_id или '' при ошибке."""
        p = Path(video_path)
        if not p.is_file():
            logger.error("Видео не найдено: %s", p)
            return ""
        width, height = await async_probe_video_dimensions(video_path)
        try:
            msg = await self._bot.send_video(
                chat_id=settings.telegram.chat_id,
                video=FSInputFile(str(p), filename=p.name),
                caption=caption,
                supports_streaming=True,
                width=width,
                height=height,
            )
            file_id: str = msg.video.file_id if msg.video else ""
            logger.debug("Видео загружено в канал: file_id=%s", file_id)
            return file_id
        except Exception:
            logger.exception("upload_video_to_channel failed")
            return ""
