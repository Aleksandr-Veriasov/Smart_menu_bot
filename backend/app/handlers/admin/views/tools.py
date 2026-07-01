"""admin: служебные инструменты (бэкфилл, дедупликация ингредиентов)."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_ingredient_service
from backend.app.core.templates import templates
from packages.schemas.ingredient import DupGroup
from packages.services.ingredient_service import IngredientService

router = APIRouter(prefix="/tools")

_MAX_LIMIT = 100
_ServiceDep = Annotated[IngredientService, Depends(get_ingredient_service)]


def _drop_pair_from_snapshot(ai_snapshot: str | None, canonical_id: int, duplicate_id: int) -> list[DupGroup] | None:
    """Убрать одну пару (canonical, duplicate) из ранее полученного ИИ-списка, без нового LLM-вызова.

    ai_snapshot — JSON-слепок ai_groups, переданный обратно формой. canonical_id — тот вариант,
    который админ выбрал радио-кнопкой (не обязательно первый в снапшоте). Если после удаления
    в группе остаётся меньше 2 вариантов, группа убирается целиком.
    """
    if not ai_snapshot:
        return None
    try:
        raw_groups = json.loads(ai_snapshot)
    except json.JSONDecodeError:
        return None

    result: list[DupGroup] = []
    for raw_group in raw_groups:
        variants = [tuple(v) for v in raw_group["variants"]]
        ids = {v[0] for v in variants}
        if canonical_id in ids and duplicate_id in ids:
            variants = [v for v in variants if v[0] != duplicate_id]
            variants.sort(key=lambda v: v[0] != canonical_id)
        if len(variants) >= 2:
            result.append(DupGroup(lower_name=raw_group["lower_name"], variants=variants))
    return result


def _serialize_ai_groups(ai_groups: list[DupGroup] | None) -> str:
    """JSON-слепок ai_groups для передачи через скрытое поле формы (без повторного LLM-вызова)."""
    if not ai_groups:
        return ""
    return json.dumps(
        [{"lower_name": g.lower_name, "variants": [list(v) for v in g.variants]} for g in ai_groups],
        ensure_ascii=False,
    )


def _render_dedup(
    request: Request,
    *,
    groups: list[DupGroup],
    ai_groups: list[DupGroup] | None,
    merged: dict | None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "tools/dedup.html",
        {
            "admin_login": current_login(request),
            "groups": groups,
            "ai_groups": ai_groups,
            "ai_groups_json": _serialize_ai_groups(ai_groups),
            "merged": merged,
        },
    )


@router.get("/dedup", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_page(request: Request, service: _ServiceDep) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    groups = await service.find_dup_groups()
    return _render_dedup(request, groups=groups, ai_groups=None, merged=None)


@router.post("/dedup/merge", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_merge(
    request: Request,
    service: _ServiceDep,
    canonical_id: int = Form(...),
    duplicate_id: int = Form(...),
    ai_snapshot: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    merged_info = await service.merge_duplicate(canonical_id, duplicate_id)
    groups = await service.find_dup_groups()
    ai_groups = _drop_pair_from_snapshot(ai_snapshot, canonical_id, duplicate_id)
    return _render_dedup(request, groups=groups, ai_groups=ai_groups, merged=merged_info)


@router.post("/dedup/reject", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_reject(
    request: Request,
    service: _ServiceDep,
    canonical_id: int = Form(...),
    duplicate_id: int = Form(...),
    ai_snapshot: str | None = Form(None),
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    await service.reject_pair(canonical_id, duplicate_id)
    groups = await service.find_dup_groups()
    ai_groups = _drop_pair_from_snapshot(ai_snapshot, canonical_id, duplicate_id)
    return _render_dedup(request, groups=groups, ai_groups=ai_groups, merged=None)


@router.post("/dedup/suggest", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_suggest(request: Request, service: _ServiceDep) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    ai_groups = await service.suggest_dup_groups()
    groups = await service.find_dup_groups()
    return _render_dedup(request, groups=groups, ai_groups=ai_groups, merged=None)


_BACKFILL_FORMATS = {"old", "partial"}
_DEFAULT_FORMAT = "old"


@router.get("/backfill", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def backfill_page(request: Request, service: _ServiceDep) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    stats = await service.format_stats()
    return templates.TemplateResponse(
        request,
        "tools/backfill.html",
        {"admin_login": current_login(request), "stats": stats, "result": None, "fmt": _DEFAULT_FORMAT},
    )


@router.post("/backfill", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def backfill_run(
    request: Request,
    service: _ServiceDep,
    dry_run: bool = Form(False),
    limit: int = Form(10),
    fmt: str = Form(_DEFAULT_FORMAT),
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    if fmt not in _BACKFILL_FORMATS:
        fmt = _DEFAULT_FORMAT
    limit = max(1, min(limit, _MAX_LIMIT))
    result = await service.run_backfill(limit=limit, dry_run=dry_run, fmt=fmt)
    stats = await service.format_stats()
    return templates.TemplateResponse(
        request,
        "tools/backfill.html",
        {"admin_login": current_login(request), "stats": stats, "result": result, "fmt": fmt},
    )
