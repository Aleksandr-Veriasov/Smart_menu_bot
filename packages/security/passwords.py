from __future__ import annotations

import hmac
from typing import Optional

from passlib.context import CryptContext

from packages.common_settings.settings import settings

try:
    # если есть общесистемный перец (pepper), берём из настроек
    _PEPPER: Optional[str] = (
        settings.security.password_pepper.get_secret_value()
        if settings.security.password_pepper
        else None
    )
except Exception:
    _PEPPER = None

_pwd_ctx = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # баланс безопасность/скорость
)


def _with_pepper(raw: str) -> str:
    if not _PEPPER:
        return raw
    # HMAC как примесь перед хэшированием: стойко и детерминированно
    return hmac.new(
        _PEPPER.encode("utf-8"), raw.encode("utf-8"), "sha256"
    ).hexdigest()


def hash_password(raw_password: str) -> str:
    """Вернёт bcrypt-хэш. Соль уникальна и вшита в результат."""
    material = _with_pepper(raw_password)
    return str(_pwd_ctx.hash(material))


def verify_password(raw_password: str, stored_hash: str) -> bool:
    """Проверка пароля против хэша."""
    material = _with_pepper(raw_password)
    return bool(_pwd_ctx.verify(material, stored_hash))


def needs_rehash(stored_hash: str) -> bool:
    """Полезно при смене параметров/алгоритма."""
    return bool(_pwd_ctx.needs_update(stored_hash))
