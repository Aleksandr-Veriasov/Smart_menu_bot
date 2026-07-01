"""admin: список, создание, редактирование и удаление ингредиентов."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_ingredient_service
from backend.app.core.templates import templates
from packages.services.ingredient_service import IngredientService

router = APIRouter(prefix="/ingredients")

_PAGE_SIZE = 30
_ServiceDep = Annotated[IngredientService, Depends(get_ingredient_service)]


@router.get("", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def ingredients_list(
    request: Request, service: _ServiceDep, page: int = 1, q: str = ""
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    ingredients, total = await service.list_page(page, _PAGE_SIZE, q)
    return templates.TemplateResponse(
        request,
        "ingredients/list.html",
        {
            "admin_login": current_login(request),
            "ingredients": ingredients,
            "q": q,
            "page": page,
            "total": total,
            "total_pages": max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE),
        },
    )


@router.get("/new", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def ingredient_new_form(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "ingredients/form.html",
        {"admin_login": current_login(request), "ingredient": None, "error": None},
    )


@router.post("/new", response_model=None, include_in_schema=False)
async def ingredient_create(
    request: Request, service: _ServiceDep, name: str = Form(...)
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect
    name = name.strip()
    if not name:
        return templates.TemplateResponse(
            request,
            "ingredients/form.html",
            {"admin_login": current_login(request), "ingredient": None, "error": "Название обязательно"},
        )
    try:
        await service.create(name)
    except ValueError as e:
        return templates.TemplateResponse(
            request,
            "ingredients/form.html",
            {"admin_login": current_login(request), "ingredient": None, "error": str(e)},
        )
    return RedirectResponse(url="/admin/ingredients", status_code=303)


@router.get("/{ing_id}/edit", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def ingredient_edit_form(request: Request, service: _ServiceDep, ing_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        ing = await service.get_or_raise(ing_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return templates.TemplateResponse(
        request,
        "ingredients/form.html",
        {"admin_login": current_login(request), "ingredient": ing, "error": None},
    )


@router.post("/{ing_id}/edit", response_model=None, include_in_schema=False)
async def ingredient_update(
    request: Request, service: _ServiceDep, ing_id: int, name: str = Form(...)
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect
    name = name.strip()
    if not name:
        try:
            ing = await service.get_or_raise(ing_id)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        return templates.TemplateResponse(
            request,
            "ingredients/form.html",
            {"admin_login": current_login(request), "ingredient": ing, "error": "Название обязательно"},
        )
    try:
        await service.update(ing_id, name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        try:
            ing = await service.get_or_raise(ing_id)
        except LookupError as e2:
            raise HTTPException(status_code=404, detail=str(e2)) from None
        return templates.TemplateResponse(
            request,
            "ingredients/form.html",
            {"admin_login": current_login(request), "ingredient": ing, "error": str(e)},
        )
    return RedirectResponse(url="/admin/ingredients", status_code=303)


@router.post("/{ing_id}/delete", response_model=None, include_in_schema=False)
async def ingredient_delete(request: Request, service: _ServiceDep, ing_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    await service.delete(ing_id)
    return RedirectResponse(url="/admin/ingredients", status_code=303)
