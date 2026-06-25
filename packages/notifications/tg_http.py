"""Синхронный HTTP-клиент для Telegram Bot API.

Используется в media_worker и любом другом контексте без aiogram.
Не тянет aiogram/asyncio — только requests.
"""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_NOT_MODIFIED = "message is not modified"


def is_not_modified(description: str) -> bool:
    return _NOT_MODIFIED in description.lower()


def format_error_text(text: str) -> str:
    return f"❌ {text}"


class TgBotHttpClient:
    """Тонкая обёртка над Bot API: call / edit_message / send_message / edit_or_send."""

    def __init__(self, bot_token: str, timeout: int = 10) -> None:
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._timeout = timeout

    def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Выполнить произвольный Bot API метод. Возвращает None при сетевой ошибке."""
        try:
            r = requests.post(f"{self._base}/{method}", json=payload, timeout=self._timeout)
            data: dict[str, Any] = r.json()
            if not data.get("ok"):
                logger.warning("Bot API %s error: %s", method, data.get("description"))
            return data
        except Exception:
            logger.exception("Bot API %s failed", method)
            return None

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> bool:
        """Редактировать сообщение. Возвращает True при успехе или 'not modified'."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = self.call("editMessageText", payload)
        if resp is None:
            return False
        if not resp.get("ok"):
            return is_not_modified(resp.get("description", ""))
        return True

    def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> int | None:
        """Отправить новое сообщение. Возвращает message_id или None."""
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = self.call("sendMessage", payload)
        if resp and resp.get("ok"):
            return resp["result"]["message_id"]
        return None

    def edit_or_send(
        self,
        chat_id: int,
        message_id: int | None,
        text: str,
        **kwargs: Any,
    ) -> int | None:
        """Попробовать отредактировать; если нет message_id или ошибка — отправить новое."""
        if message_id is not None and self.edit_message(chat_id, message_id, text, **kwargs):
            return message_id
        return self.send_message(chat_id, text, **kwargs)
