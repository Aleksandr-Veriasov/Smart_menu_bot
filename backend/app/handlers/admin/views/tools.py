"""admin: служебные инструменты (бэкфилл, дедупликация ингредиентов)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_ingredient_service
from backend.app.core.templates import templates
from packages.services.ingredient_service import IngredientService

router = APIRouter(prefix="/tools")

_MAX_LIMIT = 100
_ServiceDep = Annotated[IngredientService, Depends(get_ingredient_service)]


@router.get("/dedup", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_page(request: Request, service: _ServiceDep) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    groups = await service.find_dup_groups()
    return templates.TemplateResponse(
        request,
        "tools/dedup.html",
        {"admin_login": current_login(request), "groups": groups, "merged": None},
    )


@router.post("/dedup/merge", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_merge(
    request: Request,
    service: _ServiceDep,
    canonical_id: int = Form(...),
    duplicate_id: int = Form(...),
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    merged_info = await service.merge_duplicate(canonical_id, duplicate_id)
    groups = await service.find_dup_groups()
    return templates.TemplateResponse(
        request,
        "tools/dedup.html",
        {"admin_login": current_login(request), "groups": groups, "merged": merged_info},
    )


@router.get("/backfill", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def backfill_page(request: Request, service: _ServiceDep) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    pending_count = await service.count_pending_backfill()
    return templates.TemplateResponse(
        request,
        "tools/backfill.html",
        {"admin_login": current_login(request), "pending_count": pending_count, "result": None},
    )


@router.post("/backfill", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def backfill_run(
    request: Request,
    service: _ServiceDep,
    dry_run: bool = Form(False),
    limit: int = Form(10),
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    limit = max(1, min(limit, _MAX_LIMIT))
    result = await service.run_backfill(limit=limit, dry_run=dry_run)
    pending_count = await service.count_pending_backfill()
    return templates.TemplateResponse(
        request,
        "tools/backfill.html",
        {"admin_login": current_login(request), "pending_count": pending_count, "result": result},
    )
