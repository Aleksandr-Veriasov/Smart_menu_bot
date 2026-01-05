# app/notifications/telegram_notifier.py
import asyncio
import logging
import time
from typing import Any

from telegram import Bot
from telegram.error import BadRequest

from bot.app.core.types import PTBContext
from packages.notifications.base import Notifier

logger = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """
    Держит одно сообщение статуса и редактирует его.
    Первый вызов info() отправляет сообщение и запоминает message_id.
    Дальше info()/progress()/error() редактируют этот же месседж.
    """

    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        *,
        min_edit_interval: float = 0.9,
        context: PTBContext,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.context = context
        # гарантируем, что user_data — словарь, а не None (и типам будет ок)
        if self.context.user_data is None:
            self.context.user_data = {}
        # для удобства держим ссылку
        self.user_data: dict[Any, Any] = self.context.user_data

        self.message_id: int | None = self.user_data.get("progress_msg_id")
        self._last_edit_ts = 0.0
        self._min_edit_interval = min_edit_interval
        self._closed = False
        self._last_pct: int | None = None
        self._last_text: str = ""

    # ---------- публичный контракт ----------

    async def info(self, text: str) -> None:
        if self.message_id is None:
            msg = await self.bot.send_message(self.chat_id, text)
            self.message_id = msg.message_id
            self.user_data["progress_msg_id"] = self.message_id
        else:
            try:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    text=text,
                )
            except BadRequest as e:
                msq_str = str(e).lower()
                if "not modified" in msq_str:
                    return
                logger.warning("Не удалось отредактировать сообщение: %s", e)
                if "message to edit not found" or "message can't be edited" in msq_str:
                    new_msg = await self.bot.send_message(self.chat_id, text)
                    self.message_id = new_msg.message_id
                    return
                raise

    async def progress(self, pct: int, text: str = "") -> None:
        if self._closed:
            return
        self._last_pct = max(0, min(100, int(pct)))
        label = text or self._last_text or ""
        content = self._render(self._last_pct, label)
        await self._safe_edit(content)

    async def error(self, text: str) -> None:
        if self._closed:
            return
        self._closed = True
        content = f"❌ {text}"
        if self.message_id is None:
            await self._safe_send(content)
        else:
            await self._safe_edit(content, force=True)

    # ---------- внутренние хелперы ----------

    async def _safe_send(self, text: str) -> Any | None:
        try:
            return await self.bot.send_message(self.chat_id, text)
        except Exception as e:
            logger.warning("Не удалось отправить сообщение в Telegram: %s", e)
            return None

    async def _safe_edit(self, text: str, *, force: bool = False) -> None:
        # дросселирование, чтобы не упереться в лимиты
        now = time.monotonic()
        if not force and (now - self._last_edit_ts) < self._min_edit_interval:
            await asyncio.sleep(self._min_edit_interval - (now - self._last_edit_ts))

        if self.message_id is None:
            # если по какой-то причине id ещё нет — шлём новое
            msg = await self._safe_send(text)
            if msg:
                self.message_id = msg.message_id
                self._last_text = text
                self._last_edit_ts = time.monotonic()
            return

        if text == self._last_text:
            return  # нечего редактировать

        try:
            await self.bot.edit_message_text(chat_id=self.chat_id, message_id=self.message_id, text=text)
            self._last_text = text
            self._last_edit_ts = time.monotonic()
        except BadRequest as e:
            # частые случаи: 'Message is not modified' или
            # старый контент равен новому
            if "not modified" in str(e).lower():
                return
            logger.warning("Не удалось отредактировать сообщение: %s", e)
        except Exception as e:
            logger.warning("Ошибка при редактировании сообщения: %s", e)

    def _render(self, pct: int | None, label: str) -> str:
        """Текст + простая прогресс‑бар линия."""
        if pct is None:
            return label or "⏳ Готовим…"

        total = 10  # 10 сегментов
        filled = int(round((pct / 100) * total))
        bar = "█" * filled + "░" * (total - filled)
        label_part = f" — {label}" if label else ""
        return f"▶️ Прогресс: {pct}% [{bar}]{label_part}"
