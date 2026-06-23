import base64
import binascii
import hashlib
import os

from packages.common_settings.settings import settings

TOKEN_NONCE_LEN = 8


def pepper_bytes() -> bytes:
    """Возвращает секретный ключ (pepper) в байтах."""
    pepper = settings.security.password_pepper
    if not pepper:
        raise RuntimeError("PASSWORD_PEPPER не задан")
    return pepper.get_secret_value().encode("utf-8")


def derive_keystream(pepper: bytes, nonce: bytes, length: int) -> bytes:
    """Детерминированно строит псевдослучайный поток байт из pepper и nonce."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        counter_bytes = counter.to_bytes(4, "big", signed=False)
        block = hashlib.sha256(pepper + nonce + counter_bytes).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def urlsafe_b64encode_nopad(data: bytes) -> str:
    """Кодирует байты в urlsafe-base64 без завершающего padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def urlsafe_b64decode_padded(data: str) -> bytes:
    """Декодирует urlsafe-base64, автоматически восстанавливая padding."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def encrypt_recipe_id(recipe_id: str) -> str:
    """Шифрует recipe_id в токен для шаринга."""
    pepper = pepper_bytes()
    nonce = os.urandom(TOKEN_NONCE_LEN)
    plaintext = recipe_id.encode("utf-8")
    stream = derive_keystream(pepper, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream, strict=False))
    return urlsafe_b64encode_nopad(nonce + ciphertext)


def decrypt_recipe_id(token: str) -> str | None:
    """Дешифрует токен и возвращает recipe_id или None, если не удалось."""
    try:
        raw = urlsafe_b64decode_padded(token)
        if len(raw) <= TOKEN_NONCE_LEN:
            return None
        nonce = raw[:TOKEN_NONCE_LEN]
        ciphertext = raw[TOKEN_NONCE_LEN:]
        pepper = pepper_bytes()
        stream = derive_keystream(pepper, nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream, strict=False))
        return plaintext.decode("utf-8").strip()
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
