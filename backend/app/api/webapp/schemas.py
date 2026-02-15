"""Pydantic-схемы для эндпоинтов Telegram WebApp."""

from pydantic import BaseModel, Field


class WebAppRecipeRead(BaseModel):
    """Рецепт, который отдаём в Telegram WebApp."""

    id: int
    title: str
    description: str | None = None
    category_id: int = Field(..., description="Текущая категория (для пользователя, открывшего WebApp)")
    ingredients: list[str] = Field(default_factory=list)


class WebAppRecipePatch(BaseModel):
    """PATCH-пейлоад из Telegram WebApp. Все поля опциональные."""

    title: str | None = None
    description: str | None = None
    category_id: int | None = None
    ingredients_text: str | None = None


class WebAppRecipeDraft(BaseModel):
    """Короткоживущий черновик в Redis на время навигации в WebApp."""

    title: str | None = None
    category_id: int | None = None


class WebAppCategoryRead(BaseModel):
    """Категория, которую отдаём в Telegram WebApp."""

    id: int
    name: str
    slug: str | None = None
