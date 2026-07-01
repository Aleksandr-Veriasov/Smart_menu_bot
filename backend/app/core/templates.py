"""Singleton Jinja2Templates для admin."""

from decimal import Decimal

from fastapi.templating import Jinja2Templates

from packages.utils import normalize_quantity

templates = Jinja2Templates(directory="backend/web/templates/admin")


def _fmt_qty(value: Decimal | None) -> str:
    """Отформатировать количество без незначащих нулей: Decimal('2.000') → '2', '1.500' → '1.5'."""
    if value is None:
        return ""
    return str(normalize_quantity(value))


templates.env.filters["qty"] = _fmt_qty
