"""Тесты validate_telegram_webapp_init_data."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from backend.app.handlers.webapp.tg_webapp_auth import (
    TelegramWebAppUser,
    validate_telegram_webapp_init_data,
)

_BOT_TOKEN = "1234567890:AABBCCDDEEFFaabbccddeeff-TestToken"
_USER_ID = 99


def _build_init_data(
    *,
    bot_token: str = _BOT_TOKEN,
    auth_date: int | None = None,
    user_id: int = _USER_ID,
    corrupt_hash: bool = False,
    omit_hash: bool = False,
) -> str:
    """Собрать корректный initData и опционально сломать его."""
    if auth_date is None:
        auth_date = int(time.time())

    user_json = json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":"))
    fields: dict[str, str] = {
        "auth_date": str(auth_date),
        "user": user_json,
    }

    items = sorted(fields.items())
    data_check_string = "\n".join(f"{k}={v}" for k, v in items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not omit_hash:
        if corrupt_hash:
            computed_hash = "0" * len(computed_hash)
        fields["hash"] = computed_hash

    return urlencode(fields)


class TestValidInitData:
    def test_returns_correct_user_id(self) -> None:
        init_data = _build_init_data()
        user = validate_telegram_webapp_init_data(init_data, bot_token=_BOT_TOKEN)
        assert isinstance(user, TelegramWebAppUser)
        assert user.id == _USER_ID

    def test_custom_user_id(self) -> None:
        init_data = _build_init_data(user_id=12345)
        user = validate_telegram_webapp_init_data(init_data, bot_token=_BOT_TOKEN)
        assert user.id == 12345


class TestExpiredInitData:
    def test_expired_raises_401(self) -> None:
        old_auth_date = int(time.time()) - 25 * 3600  # старше 24 часов
        init_data = _build_init_data(auth_date=old_auth_date)
        with pytest.raises(HTTPException) as exc_info:
            validate_telegram_webapp_init_data(init_data, bot_token=_BOT_TOKEN, max_age_sec=24 * 3600)
        assert exc_info.value.status_code == 401
        assert "истёк" in exc_info.value.detail

    def test_fresh_data_is_accepted(self) -> None:
        init_data = _build_init_data(auth_date=int(time.time()) - 60)
        user = validate_telegram_webapp_init_data(init_data, bot_token=_BOT_TOKEN, max_age_sec=3600)
        assert user.id == _USER_ID

    def test_custom_max_age(self) -> None:
        init_data = _build_init_data(auth_date=int(time.time()) - 120)
        with pytest.raises(HTTPException) as exc_info:
            validate_telegram_webapp_init_data(init_data, bot_token=_BOT_TOKEN, max_age_sec=60)
        assert exc_info.value.status_code == 401


class TestWrongSignature:
    def test_corrupted_hash_raises_401(self) -> None:
        init_data = _build_init_data(corrupt_hash=True)
        with pytest.raises(HTTPException) as exc_info:
            validate_telegram_webapp_init_data(init_data, bot_token=_BOT_TOKEN)
        assert exc_info.value.status_code == 401
        assert "подпись" in exc_info.value.detail

    def test_wrong_bot_token_raises_401(self) -> None:
        init_data = _build_init_data()
        with pytest.raises(HTTPException) as exc_info:
            validate_telegram_webapp_init_data(init_data, bot_token="9999999999:WrongToken")
        assert exc_info.value.status_code == 401


class TestMissingHash:
    def test_no_hash_field_raises_401(self) -> None:
        init_data = _build_init_data(omit_hash=True)
        with pytest.raises(HTTPException) as exc_info:
            validate_telegram_webapp_init_data(init_data, bot_token=_BOT_TOKEN)
        assert exc_info.value.status_code == 401
        assert "hash" in exc_info.value.detail.lower()
