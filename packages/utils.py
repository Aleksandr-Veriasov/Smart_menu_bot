from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation


def normalize_quantity(value: Decimal) -> Decimal:
    """Убрать незначащие нули после запятой: 2.00 → 2, 1.50 → 1.5, 100 → 100 (без экспоненты)."""
    normalized = value.normalize()
    return normalized.quantize(Decimal(1)) if normalized == normalized.to_integral_value() else normalized


def format_qty_unit(quantity: Decimal | None, unit: str | None) -> str:
    """Собрать «кол-во ед.» без незначащих нулей: (2.000, 'шт') → '2 шт', (None, 'по вкусу') → 'по вкусу'."""
    parts: list[str] = []
    if quantity is not None:
        parts.append(str(normalize_quantity(quantity)))
    if unit:
        parts.append(unit)
    return " ".join(parts)


def parse_decimal_form(raw: str) -> Decimal | None:
    """Распарсить строку из HTML-формы в Decimal. Вернуть None если пусто или невалидно."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return normalize_quantity(Decimal(raw))
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
