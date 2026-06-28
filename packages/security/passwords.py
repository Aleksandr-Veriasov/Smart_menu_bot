import hmac

import bcrypt

from packages.common_settings.settings import settings

try:
    _PEPPER: str | None = (
        settings.security.password_pepper.get_secret_value() if settings.security.password_pepper else None
    )
except Exception:
    _PEPPER = None

_ROUNDS = 12


def _with_pepper(raw: str) -> str:
    if not _PEPPER:
        return raw
    return hmac.new(_PEPPER.encode("utf-8"), raw.encode("utf-8"), "sha256").hexdigest()


def hash_password(raw_password: str) -> str:
    material = _with_pepper(raw_password)
    return bcrypt.hashpw(material.encode(), bcrypt.gensalt(rounds=_ROUNDS)).decode()


def verify_password(raw_password: str, stored_hash: str) -> bool:
    material = _with_pepper(raw_password)
    try:
        return bcrypt.checkpw(material.encode(), stored_hash.encode())
    except Exception:
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        parts = stored_hash.split("$")
        return len(parts) < 3 or int(parts[2]) != _ROUNDS
    except Exception:
        return True
