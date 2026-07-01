from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from packages.db.models import Recipe


class IngredientItemRead(BaseModel):
    """Ингредиент с количеством и единицей для отображения в WebApp."""

    name: str
    quantity: Decimal | None = None
    unit: str | None = None


class IngredientItemWrite(BaseModel):
    """Ингредиент с количеством и единицей для записи из WebApp."""

    name: str
    quantity: Decimal | None = None
    unit: str | None = None


class WebAppRecipeRead(BaseModel):
    """Рецепт, который отдаём в Telegram WebApp."""

    id: int
    title: str
    description: str | None = None
    category_id: int = Field(..., description="Текущая категория (для пользователя, открывшего WebApp)")
    ingredients: list[str] = Field(default_factory=list)  # легаси, имена для старого фронта
    ingredient_details: list[IngredientItemRead] = Field(default_factory=list)  # новый фронт (C5)

    @classmethod
    def from_recipe(cls, recipe: Recipe, *, category_id: int) -> WebAppRecipeRead:
        ingredients = [str(i.name) for i in (recipe.ingredients or []) if getattr(i, "name", None)]
        ingredient_details = [
            IngredientItemRead(
                name=str(link.ingredient.name),
                quantity=link.quantity,
                unit=link.unit,
            )
            for link in getattr(recipe, "ingredient_links", [])
            if getattr(link, "ingredient", None) and link.ingredient.name
        ]
        return cls(
            id=int(recipe.id),
            title=str(recipe.title),
            description=recipe.description,
            category_id=int(category_id),
            ingredients=ingredients,
            ingredient_details=ingredient_details,
        )


class WebAppRecipePatch(BaseModel):
    """PATCH-пейлоад из Telegram WebApp. Все поля опциональные."""

    title: str | None = None
    description: str | None = None
    category_id: int | None = None
    ingredients_text: str | None = None  # легаси: текстовый список имён
    ingredients: list[IngredientItemWrite] | None = None  # новый фронт (C5): структурированный список

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Название не может быть пустым")
        return v.strip() if v is not None else v


class WebAppRecipeDraft(BaseModel):
    """Короткоживущий черновик в Redis на время навигации в WebApp."""

    title: str | None = None
    category_id: int | None = None


class WebAppCategoryRead(BaseModel):
    """Категория, которую отдаём в Telegram WebApp."""

    id: int
    name: str
    slug: str | None = None
