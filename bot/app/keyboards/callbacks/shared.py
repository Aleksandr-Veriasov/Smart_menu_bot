import re


class SharedCallbacks:
    SLUG_PATTERN = r"[a-z0-9][a-z0-9_-]*"
    SID_PATTERN = r"[A-Za-z0-9]+"
    SEARCH_TYPE_PATTERN = r"title|ingredient"
    MENU_MODE_PATTERN = r"show|random"
    LIST_MODE_PATTERN = r"show|search"

    BOOK_SLUG_PREFIX = "book_"
    SHARED_START_PREFIX = "share:"

    @classmethod
    def build_book_slug(cls, category_slug: str) -> str:
        return f"{cls.BOOK_SLUG_PREFIX}{category_slug}"

    @classmethod
    def is_book_slug(cls, category_slug: str | None) -> bool:
        return bool(category_slug and str(category_slug).startswith(cls.BOOK_SLUG_PREFIX))

    @classmethod
    def parse_book_slug(cls, category_slug: str | None) -> str | None:
        if not cls.is_book_slug(category_slug):
            return None
        slug = str(category_slug).removeprefix(cls.BOOK_SLUG_PREFIX).strip().lower()
        return slug if re.fullmatch(cls.SLUG_PATTERN, slug) else None

    @classmethod
    def build_shared_start_payload(cls, token: str) -> str:
        return f"{cls.SHARED_START_PREFIX}{token}"

    @classmethod
    def parse_shared_start_token(cls, data: str | None) -> str | None:
        if not data or not data.startswith(cls.SHARED_START_PREFIX):
            return None
        token = data.removeprefix(cls.SHARED_START_PREFIX).strip()
        return token or None

    @classmethod
    def to_book_slug(cls, category_slug: str) -> str:
        return cls.build_book_slug(category_slug)

    @classmethod
    def _parse_prefixed_int(cls, data: str | None, prefix: str) -> int | None:
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", data or "")
        return int(match.group(1)) if match else None

    @classmethod
    def _parse_sid_and_int(cls, data: str | None, prefix: str) -> tuple[str, int] | None:
        match = re.fullmatch(rf"{re.escape(prefix)}({cls.SID_PATTERN}):(\d+)", data or "")
        if not match:
            return None
        return match.group(1), int(match.group(2))
