from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.api.deps import get_admin_service, require_admin
from packages.schemas import AdminStatsRead
from packages.services import AdminService

admin_router = APIRouter(dependencies=[Depends(require_admin)])


@admin_router.get("/stats", response_model=AdminStatsRead, tags=["admin"])
async def admin_stats(service: Annotated[AdminService, Depends(get_admin_service)]) -> AdminStatsRead:
    return await service.get_stats()
