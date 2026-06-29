from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.core.deps import get_tg_user_id, get_webapp_service
from packages.schemas import WebAppCategoryRead
from packages.services import WebAppService

router = APIRouter(prefix="/categories")

_Service = Annotated[WebAppService, Depends(get_webapp_service)]
_UserId = Annotated[int, Depends(get_tg_user_id)]


@router.get("", response_model=list[WebAppCategoryRead])
async def list_categories(_service: _Service, user_id: _UserId) -> list[WebAppCategoryRead]:
    """Список всех категорий (из кеша Redis, при необходимости с догрузкой из БД)."""
    return await _service.list_categories(user_id)
