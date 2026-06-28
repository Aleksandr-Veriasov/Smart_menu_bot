"""FastAPI-роутер для эндпоинтов Telegram WebApp (Mini App)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.deps import get_tg_user_id, get_webapp_service
from packages.schemas import (
    WebAppCategoryRead,
    WebAppRecipeDraft,
    WebAppRecipePatch,
    WebAppRecipeRead,
)
from packages.services import WebAppService

webapp_router = APIRouter()

Service = Annotated[WebAppService, Depends(get_webapp_service)]
UserId = Annotated[int, Depends(get_tg_user_id)]


@webapp_router.get("/categories", response_model=list[WebAppCategoryRead])
async def list_categories(service: Service, user_id: UserId) -> list[WebAppCategoryRead]:
    """Список всех категорий (из кеша Redis, при необходимости с догрузкой из БД)."""
    return await service.list_categories(user_id)


@webapp_router.get("/recipes/{recipe_id}", response_model=WebAppRecipeRead)
async def get_recipe(recipe_id: int, service: Service, user_id: UserId) -> WebAppRecipeRead:
    """Вернуть рецепт пользователя для редактирования в WebApp."""
    return await service.get_recipe(recipe_id, user_id)


@webapp_router.get("/recipes/{recipe_id}/draft", response_model=WebAppRecipeDraft)
async def get_recipe_draft(recipe_id: int, service: Service, user_id: UserId) -> WebAppRecipeDraft:
    """Прочитать короткоживущий черновик навигации для рецепта."""
    return await service.get_recipe_draft(recipe_id, user_id)


@webapp_router.put("/recipes/{recipe_id}/draft", response_model=WebAppRecipeDraft)
async def put_recipe_draft(
    recipe_id: int, payload: WebAppRecipeDraft, service: Service, user_id: UserId
) -> WebAppRecipeDraft:
    """Сохранить короткоживущий черновик навигации для рецепта."""
    return await service.set_recipe_draft(recipe_id, user_id, payload)


@webapp_router.delete("/recipes/{recipe_id}/draft")
async def delete_recipe_draft(recipe_id: int, service: Service, user_id: UserId) -> dict:
    """Удалить черновик навигации для рецепта."""
    await service.delete_recipe_draft(recipe_id, user_id)
    return {"ok": True}


@webapp_router.patch("/recipes/{recipe_id}", response_model=WebAppRecipeRead)
async def patch_recipe(
    recipe_id: int, payload: WebAppRecipePatch, service: Service, user_id: UserId
) -> WebAppRecipeRead:
    """Обновить поля рецепта. При необходимости клонирует общий рецепт."""
    return await service.patch_recipe(recipe_id, user_id, payload)
