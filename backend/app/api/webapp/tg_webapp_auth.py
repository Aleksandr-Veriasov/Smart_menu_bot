"""
Проверка Telegram WebApp initData.

Реализует проверку подписи initData и базовую проверку срока действия (auth_date).
Используется бекендом для эндпоинтов, которые открываются внутри Telegram WebApp (Mini App).
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import HTTPException


@dataclass(frozen=True, slots=True)
class TelegramWebAppUser:
    """Минимальный набор данных пользователя Telegram, который нужен бекенду."""

    id: int


def _parse_init_data(init_data: str) -> dict[str, str]:
    """Разобрать initData (querystring) в dict key/value."""

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    return {k: v for k, v in pairs}


def _calc_webapp_hash(*, bot_token: str, data_check_string: str) -> str:
    """
    Вычислить hash для проверки initData (Telegram WebApp).
    Алгоритм: secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token), затем hash = HMAC_SHA256(secret_key, dcs).
    """
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def validate_telegram_webapp_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_sec: int = 24 * 3600,
) -> TelegramWebAppUser:
    """
    Провалидировать Telegram WebApp initData.

    При любой ошибке поднимает HTTPException(401).
    При успехе возвращает user_id из initData.
    """

    data = _parse_init_data(init_data)
    received_hash = (data.get("hash") or "").strip().lower()
    if not received_hash:
        raise HTTPException(status_code=401, detail="Отсутствует hash в initData")

    auth_date_raw = (data.get("auth_date") or "").strip()
    try:
        auth_date = int(auth_date_raw)
    except Exception:
        # Явно убираем context исключения, чтобы не путать с ошибками в обработчике.
        raise HTTPException(status_code=401, detail="Некорректный auth_date в initData") from None

    now = int(time.time())
    if auth_date > now + 60:
        raise HTTPException(status_code=401, detail="auth_date в initData из будущего")
    if max_age_sec and (now - auth_date) > max_age_sec:
        raise HTTPException(status_code=401, detail="Срок действия initData истёк")

    items = [(k, v) for k, v in data.items() if k != "hash"]
    items.sort(key=lambda kv: kv[0])
    data_check_string = "\n".join([f"{k}={v}" for k, v in items])

    expected_hash = _calc_webapp_hash(bot_token=bot_token, data_check_string=data_check_string)
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Неверная подпись initData")

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="Отсутствует user в initData")
    try:
        user_obj = json.loads(user_raw)
        user_id = int(user_obj["id"])
    except Exception:
        raise HTTPException(status_code=401, detail="Некорректный user в initData") from None

    return TelegramWebAppUser(id=user_id)
