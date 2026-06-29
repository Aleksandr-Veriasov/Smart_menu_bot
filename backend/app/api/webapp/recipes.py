from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.core.deps import get_tg_user_id, get_webapp_service
from packages.schemas import WebAppRecipeDraft, WebAppRecipePatch, WebAppRecipeRead
from packages.services import WebAppService

router = APIRouter(prefix="/recipes")

_Service = Annotated[WebAppService, Depends(get_webapp_service)]
_UserId = Annotated[int, Depends(get_tg_user_id)]


@router.get("/{recipe_id}", response_model=WebAppRecipeRead)
async def get_recipe(recipe_id: int, service: _Service, user_id: _UserId) -> WebAppRecipeRead:
    """Вернуть рецепт пользователя для редактирования в WebApp."""
    return await service.get_recipe(recipe_id, user_id)


@router.get("/{recipe_id}/draft", response_model=WebAppRecipeDraft)
async def get_recipe_draft(recipe_id: int, service: _Service, user_id: _UserId) -> WebAppRecipeDraft:
    """Прочитать короткоживущий черновик навигации для рецепта."""
    return await service.get_recipe_draft(recipe_id, user_id)


@router.put("/{recipe_id}/draft", response_model=WebAppRecipeDraft)
async def put_recipe_draft(
    recipe_id: int, payload: WebAppRecipeDraft, service: _Service, user_id: _UserId
) -> WebAppRecipeDraft:
    """Сохранить короткоживущий черновик навигации для рецепта."""
    return await service.set_recipe_draft(recipe_id, user_id, payload)


@router.delete("/{recipe_id}/draft")
async def delete_recipe_draft(recipe_id: int, service: _Service, user_id: _UserId) -> dict:
    """Удалить черновик навигации для рецепта."""
    await service.delete_recipe_draft(recipe_id, user_id)
    return {"ok": True}


@router.patch("/{recipe_id}", response_model=WebAppRecipeRead)
async def patch_recipe(
    recipe_id: int, payload: WebAppRecipePatch, service: _Service, user_id: _UserId
) -> WebAppRecipeRead:
    """Обновить поля рецепта. При необходимости клонирует общий рецепт."""
    return await service.patch_recipe(recipe_id, user_id, payload)
