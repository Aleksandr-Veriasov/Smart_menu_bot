from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from packages.dl_protocol.schemas import Platform


def detect_platform(url: str) -> Platform:
    """Определить платформу по ссылке.

    1) Нормализуем URL (если нет схемы — добавляем https://).
    2) Если это известный редиректор IG/FB, пытаемся достать исходную ссылку.
    3) Берём hostname и проверяем по спискам.

    :param url: исходный URL (возможны формы без схемы или с редиректором)
    :return: 'instagram' или 'tiktok'
    :raises ValueError: если хост не соответствует поддерживаемым платформам
    """
    normalized = _ensure_scheme(url)
    # Попытка распаковать редиректор IG/FB, если он встречается
    unwrapped = _unwrap_known_redirectors(normalized) or normalized

    host = extract_hostname(unwrapped)
    if is_instagram_host(host):
        return 'instagram'
    if is_tiktok_host(host):
        return 'tiktok'
    raise ValueError(
        f'Неподдерживаемая платформа для URL: host={host}, url={url}'
    )


def extract_hostname(url: str) -> str:
    """Извлечь hostname из URL (в нижнем регистре).

    Если в URL отсутствует схема, временно подставляем `https://` для
    корректного парсинга.
    Возвращаем только сетевое имя (без порта).
    """
    parsed = urlparse(_ensure_scheme(url))
    # netloc может включать порт — отделим только имя хоста
    host = (parsed.hostname or '').lower()
    return host


def is_instagram_host(host: str) -> bool:
    """Проверка, относится ли hostname к Instagram.

    Учитываем базовый домен и популярные поддомены/редиректоры.
    """
    h = (host or '').lower()
    if not h:
        return False
    if h == 'instagram.com' or h.endswith('.instagram.com'):
        return True
    # Короткие/смежные IG-домены
    if h in {'ig.me'}:
        return True
    # Редиректоры IG/FB — сами по себе не платформа, но мы их разворачиваем
    if h in {
        'l.instagram.com', 'lm.instagram.com',
        'l.facebook.com', 'lm.facebook.com'
    }:
        return True
    return False


def is_tiktok_host(host: str) -> bool:
    """Проверка, относится ли hostname к TikTok.

    Учитываем базовый домен и короткие домены для шаринга.
    """
    h = (host or '').lower()
    if not h:
        return False
    if h == 'tiktok.com' or h.endswith('.tiktok.com'):
        return True
    # Короткие домены/редиректоры TikTok
    if h in {'vm.tiktok.com', 'vt.tiktok.com'}:
        return True
    return False


def _ensure_scheme(url: str) -> str:
    """Убедиться, что в URL есть схема.

    Если пользователь прислал `instagram.com/reel/...` без `https://`,
    `urlparse` воспринимает это как путь. Добавляем `https://` в таких случаях.
    """
    if '://' in url:
        return url
    return f'https://{url}'


def _unwrap_known_redirectors(url: str) -> Optional[str]:
    """Развернуть известные редиректоры IG/FB до исходной ссылки.

    Речь о ссылках вида `https://l.instagram.com/?u=<enc_url>&...` или
    `https://l.facebook.com/l.php?u=<enc_url>`.
    Если формат не совпадает или параметр `u` отсутствует — возвращаем `None`.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if host not in {
        'l.instagram.com', 'lm.instagram.com',
        'l.facebook.com', 'lm.facebook.com'
    }:
        return None

    qs = parse_qs(parsed.query)
    u_vals = qs.get('u') or qs.get('U')
    if not u_vals:
        return None

    # Берём первый `u`, декодируем и возвращаем
    try:
        target = unquote(u_vals[0])
        # Если внутри снова нет схемы, добавим для устойчивости
        return _ensure_scheme(target)
    except Exception:
        return None
