"""Общие утилиты форматирования для Telegram-нотификаторов.

Чистые функции без внешних зависимостей — могут использоваться
как из bot (aiogram), так и из media_worker (plain requests).
"""

from html import escape
from typing import Any


def format_progress_bar(pct: int, label: str = "") -> str:
    """Текстовый прогресс-бар: '▶️ Прогресс: 40% [████░░░░░░] — label'."""
    pct = max(0, min(100, pct))
    filled = int(round(pct / 10))
    bar = "█" * filled + "░" * (10 - filled)
    suffix = f" — {label}" if label else ""
    return f"▶️ Прогресс: {pct}% [{bar}]{suffix}"


def format_recipe_html(
    title: str,
    recipe: str,
    ingredients: list[str] | str,
) -> str:
    """HTML-карточка рецепта для sendMessage / editMessageText."""
    if isinstance(ingredients, list):
        ing_block = "\n".join(f"• {escape(i)}" for i in ingredients)
    else:
        ing_block = escape(str(ingredients))

    return (
        f"<b>{escape(title)}</b>\n\n" f"<b>Ингредиенты:</b>\n{ing_block}\n\n" f"<b>Приготовление:</b>\n{escape(recipe)}"
    )


def save_keyboard_dict(pipeline_id: int) -> dict[str, Any]:
    """inline_keyboard-dict совместимый с aiogram SaveCB(prefix='save').

    Callback data: 'save:{action}:{pipeline_id}'
    """
    return {
        "inline_keyboard": [
            [{"text": "✅ Сохранить рецепт", "callback_data": f"save:start:{pipeline_id}"}],
            [{"text": "❌ Отмена", "callback_data": f"save:cancel:{pipeline_id}"}],
        ]
    }
