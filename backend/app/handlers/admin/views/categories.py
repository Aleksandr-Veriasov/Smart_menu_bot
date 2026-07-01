"""admin: CRUD категорий с инвалидацией Redis-кэша."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_category_service
from backend.app.core.templates import templates
from packages.services.category_service import CategoryService

router = APIRouter(prefix="/categories")

_ServiceDep = Annotated[CategoryService, Depends(get_category_service)]


# ── Список ────────────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def categories_list(request: Request, service: _ServiceDep) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    categories = await service.get_all_category()
    recipe_counts = await service.get_recipe_counts()
    return templates.TemplateResponse(
        request,
        "categories/list.html",
        {"admin_login": current_login(request), "categories": categories, "recipe_counts": recipe_counts},
    )


# ── Создание ──────────────────────────────────────────────────────────────────


@router.get("/new", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def category_new_form(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "categories/form.html",
        {"admin_login": current_login(request), "category": None, "error": None},
    )


@router.post("/new", response_model=None, include_in_schema=False)
async def category_create(
    request: Request,
    service: _ServiceDep,
    name: str = Form(...),
    slug: str = Form(""),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect
    name, slug_val = name.strip(), slug.strip() or None
    if not name:
        return templates.TemplateResponse(
            request,
            "categories/form.html",
            {"admin_login": current_login(request), "category": None, "error": "Название обязательно"},
        )
    await service.create(name=name, slug=slug_val)
    return RedirectResponse(url="/admin/categories", status_code=303)


# ── Редактирование ────────────────────────────────────────────────────────────


@router.get("/{cat_id}/edit", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def category_edit_form(request: Request, service: _ServiceDep, cat_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        cat = await service.get_or_raise(cat_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return templates.TemplateResponse(
        request,
        "categories/form.html",
        {"admin_login": current_login(request), "category": cat, "error": None},
    )


@router.post("/{cat_id}/edit", response_model=None, include_in_schema=False)
async def category_update(
    request: Request,
    service: _ServiceDep,
    cat_id: int,
    name: str = Form(...),
    slug: str = Form(""),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect
    name, slug_val = name.strip(), slug.strip() or None
    if not name:
        try:
            cat = await service.get_or_raise(cat_id)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        return templates.TemplateResponse(
            request,
            "categories/form.html",
            {"admin_login": current_login(request), "category": cat, "error": "Название обязательно"},
        )
    try:
        await service.update(cat_id, name=name, slug=slug_val)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return RedirectResponse(url="/admin/categories", status_code=303)


# ── Удаление ──────────────────────────────────────────────────────────────────


@router.post("/{cat_id}/delete", response_model=None, include_in_schema=False)
async def category_delete(request: Request, service: _ServiceDep, cat_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    await service.delete(cat_id)
    return RedirectResponse(url="/admin/categories", status_code=303)
