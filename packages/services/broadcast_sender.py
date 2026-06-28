"""Утилиты отправки broadcast-сообщений через Bot API.

Не содержит I/O — только чистые функции классификации ошибок и расчёта backoff.
Это позволяет тестировать их без HTTP-моков и БД.
"""

import random
from enum import Enum

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
