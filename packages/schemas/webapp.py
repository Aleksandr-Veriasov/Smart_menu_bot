from decimal import Decimal

from pydantic import BaseModel, Field


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


class WebAppRecipePatch(BaseModel):
    """PATCH-пейлоад из Telegram WebApp. Все поля опциональные."""

    title: str | None = None
    description: str | None = None
    category_id: int | None = None
    ingredients_text: str | None = None  # легаси: текстовый список имён
    ingredients: list[IngredientItemWrite] | None = None  # новый фронт (C5): структурированный список


class WebAppRecipeDraft(BaseModel):
    """Короткоживущий черновик в Redis на время навигации в WebApp."""

    title: str | None = None
    category_id: int | None = None


class WebAppCategoryRead(BaseModel):
    """Категория, которую отдаём в Telegram WebApp."""

    id: int
    name: str
    slug: str | None = None
