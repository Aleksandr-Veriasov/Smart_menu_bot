"""Утилиты отправки broadcast-сообщений через Bot API."""

import asyncio
import json
import random
from enum import Enum
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from packages.db.models.broadcast import BroadcastCampaign

_BACKOFF_BASE_SEC = 30.0
_BACKOFF_MAX_SEC = 3600.0
_BACKOFF_JITTER_SEC = 5.0

_PERMANENT_PHRASES = frozenset(
    {
        "deactivated",
        "blocked by the user",
        "user is deactivated",
        "bot was blocked",
        "chat not found",
        "user not found",
        "bot was kicked",
        "have no rights",
        "not enough rights",
    }
)


class FailureKind(str, Enum):
    permanent = "permanent"  # не ретраить — пользователь недоступен
    retry = "retry"  # временная ошибка, повторить позже


def classify_failure(response: dict) -> tuple[FailureKind, float | None]:
    """Определить тип сбоя по ответу Telegram Bot API.

    Возвращает (kind, retry_after).
    retry_after — секунды ожидания (только для 429), иначе None.
    """
    error_code: int = response.get("error_code", 0)
    description: str = (response.get("description") or "").lower()
    retry_after_raw = (response.get("parameters") or {}).get("retry_after")

    if error_code == 429:
        retry_after = float(retry_after_raw) if retry_after_raw is not None else 30.0
        return FailureKind.retry, retry_after

    if error_code == 403:
        return FailureKind.permanent, None

    if error_code == 400:
        if any(phrase in description for phrase in _PERMANENT_PHRASES):
            return FailureKind.permanent, None
        return FailureKind.permanent, None

    if error_code >= 500:
        return FailureKind.retry, None

    if any(phrase in description for phrase in _PERMANENT_PHRASES):
        return FailureKind.permanent, None

    return FailureKind.retry, None


def backoff_seconds(attempt: int) -> float:
    """Экспоненциальный backoff с джиттером для broadcast retry.

    attempt=1 → ~30s, attempt=2 → ~60s, attempt=3 → ~120s, …, max 3600s.
    """
    base = min(_BACKOFF_BASE_SEC * (2 ** (attempt - 1)), _BACKOFF_MAX_SEC)
    return base + random.uniform(0, _BACKOFF_JITTER_SEC)


def _parse_json_dict(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


async def tg_call(method: str, payload: dict[str, Any], *, bot_token: str, timeout: float) -> dict[str, Any]:
    """Выполнить POST-запрос к Telegram Bot API и вернуть JSON-ответ."""
    url = f"https://api.telegram.org/bot{bot_token}/{method}"

    def _call() -> dict[str, Any]:
        r = requests.post(url, json=payload, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            data = {"ok": False, "error_code": r.status_code, "description": r.text[:300]}
        return data if isinstance(data, dict) else {"ok": False, "description": "Ответ не в формате JSON"}

    return await asyncio.to_thread(_call)


async def send_campaign_message(
    campaign: "BroadcastCampaign", *, chat_id: int, bot_token: str, timeout: float
) -> dict[str, Any]:
    """Отправить кампанию в чат: sendPhoto если есть фото, иначе sendMessage."""
    reply_markup = _parse_json_dict(campaign.reply_markup_json)
    if campaign.photo_file_id or campaign.photo_url:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": campaign.photo_file_id or campaign.photo_url,
            "caption": campaign.text,
            "parse_mode": campaign.parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await tg_call("sendPhoto", payload, bot_token=bot_token, timeout=timeout)

    payload = {
        "chat_id": chat_id,
        "text": campaign.text,
        "parse_mode": campaign.parse_mode,
        "disable_web_page_preview": bool(campaign.disable_web_page_preview),
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await tg_call("sendMessage", payload, bot_token=bot_token, timeout=timeout)
