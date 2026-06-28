"""Книжный slug категории (`book_<slug>`) — доменный хелпер без привязки к Telegram.

Используется для пометки рецептов/категорий из общей «Книги рецептов»
в состоянии списка и в callback-данных карточки рецепта.
"""

import re

_BOOK_SLUG_PREFIX = "book_"
_SLUG_PATTERN = r"[a-z0-9][a-z0-9_-]*"


def build_book_slug(category_slug: str) -> str:
    return f"{_BOOK_SLUG_PREFIX}{category_slug}"


def is_book_slug(category_slug: str | None) -> bool:
    return bool(category_slug and str(category_slug).startswith(_BOOK_SLUG_PREFIX))


def parse_book_slug(category_slug: str | None) -> str | None:
    if not is_book_slug(category_slug):
        return None
    slug = str(category_slug).removeprefix(_BOOK_SLUG_PREFIX).strip().lower()
    return slug if re.fullmatch(_SLUG_PATTERN, slug) else None
