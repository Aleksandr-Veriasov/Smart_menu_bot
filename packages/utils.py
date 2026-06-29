from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


def parse_decimal_form(raw: str) -> Decimal | None:
    """Распарсить строку из HTML-формы в Decimal. Вернуть None если пусто или невалидно."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_datetime_form(raw: str) -> datetime | None:
    """Распарсить ISO-строку из HTML-формы в UTC datetime. Вернуть None если пусто или невалидно."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=UTC)
    except ValueError:
        return None
