"""Чистые функции форматирования карточек рецептов (без зависимостей от Telegram)."""

from packages.db.models import Recipe


def build_existing_recipe_text(recipe: Recipe) -> str:
    """Формирует текст карточки рецепта."""
    ingredients_text = "\n".join(f"- {ingredient.name}" for ingredient in recipe.ingredients)
    return (
        f"🍽 <b>Название рецепта:</b> {recipe.title}\n\n"
        f"📝 <b>Рецепт:</b>\n{recipe.description}\n\n"
        f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
    )
