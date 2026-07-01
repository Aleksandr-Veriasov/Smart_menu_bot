"""Чистые функции форматирования карточек рецептов (без зависимостей от Telegram)."""

from packages.db.models import Recipe, RecipeIngredient
from packages.utils import format_qty_unit


def _format_ingredient(link: RecipeIngredient) -> str:
    """Строка ингредиента: '- Имя — 2 шт' / '- Соль — по вкусу' / '- Имя'."""
    name = link.ingredient.name
    qty = format_qty_unit(link.quantity, link.unit)
    return f"- {name} — {qty}" if qty else f"- {name}"


def build_existing_recipe_text(recipe: Recipe) -> str:
    """Формирует текст карточки рецепта."""
    ingredients_text = "\n".join(_format_ingredient(link) for link in recipe.ingredient_links)
    return (
        f"🍽 <b>Название рецепта:</b> {recipe.title}\n\n"
        f"📝 <b>Рецепт:</b>\n{recipe.description}\n\n"
        f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
    )
