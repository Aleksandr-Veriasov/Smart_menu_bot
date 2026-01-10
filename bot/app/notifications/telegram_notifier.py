# app/notifications/telegram_notifier.py
import asyncio
import logging
import time

from telegram import Bot, Message
from telegram.error import BadRequest

from bot.app.core.types import PTBContext
from bot.app.utils.context_helpers import get_redis_cli
from bot.app.utils.message_cache import append_message_id_to_cache
from packages.notifications.base import Notifier
from packages.redis.repository import ProgressMessageCacheRepository

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
        source_message: Message | None = None,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.context = context
        self._redis = get_redis_cli(context)
        self._progress_user_id = source_message.from_user.id if source_message and source_message.from_user else chat_id
        self.message_id: int | None = None
        self._last_edit_ts = 0.0
        self._min_edit_interval = min_edit_interval
        self._closed = False
        self._last_pct: int | None = None
        self._last_text: str = ""
        self._source_message = source_message

    # ---------- публичный контракт ----------

    async def info(self, text: str) -> None:
        await self._load_cached_message_id()
        if self.message_id is None:
            msg = await self.bot.send_message(self.chat_id, text)
            self.message_id = msg.message_id
            if self.message_id is not None:
                await self._store_message_id(self.message_id)
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
                    if self.message_id is not None:
                        await self._store_message_id(self.message_id)
                    return
                raise

    async def progress(self, pct: int, text: str = "") -> None:
        if self._closed:
            return
        await self._load_cached_message_id()
        self._last_pct = max(0, min(100, int(pct)))
        label = text or self._last_text or ""
        content = self._render(self._last_pct, label)
        await self._safe_edit(content)

    async def error(self, text: str) -> None:
        if self._closed:
            return
        await self._load_cached_message_id()
        self._closed = True
        content = f"❌ {text}"
        if self.message_id is None:
            await self._safe_send(content)
        else:
            await self._safe_edit(content, force=True)
        await self.finalize()

    # ---------- внутренние хелперы ----------

    async def _safe_send(self, text: str) -> Message | None:
        try:
            msg = await self.bot.send_message(self.chat_id, text)
            if msg:
                await self._store_message_id(msg.message_id)
            return msg
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
                await self._store_message_id(self.message_id)
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

    async def _load_cached_message_id(self) -> None:
        """Загружает message_id из кеша, если он там есть."""
        if self.message_id is not None:
            return
        state = await ProgressMessageCacheRepository.get(self._redis, self._progress_user_id) or {}
        msg_id = state.get("message_id")
        if isinstance(msg_id, int):
            self.message_id = msg_id

    async def _store_message_id(self, message_id: int) -> None:
        """Сохраняет message_id в кеш."""
        await ProgressMessageCacheRepository.set(self._redis, self._progress_user_id, {"message_id": message_id})

    async def finalize(self) -> None:
        """Вызывается в конце, чтобы почистить кеш."""
        if self.message_id is None:
            return
        if self._source_message is not None:
            await append_message_id_to_cache(self._source_message, self.context, self.message_id)
        await ProgressMessageCacheRepository.delete(self._redis, self._progress_user_id)
