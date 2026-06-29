"""admin: список, детали и inline-редактор ингредиентов рецептов."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_recipe_service
from backend.app.core.templates import templates
from packages.recipes_core.units import ALLOWED_UNITS
from packages.services.recipe_service import RecipeService
from packages.utils import parse_decimal_form

router = APIRouter(prefix="/recipes")

_PAGE_SIZE = 25
_ServiceDep = Annotated[RecipeService, Depends(get_recipe_service)]


# ── Список ────────────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def recipes_list(
    request: Request, service: _ServiceDep, page: int = 1, q: str = ""
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    recipes, total = await service.list_page(page, _PAGE_SIZE, q)
    return templates.TemplateResponse(
        request,
        "recipes/list.html",
        {
            "admin_login": current_login(request),
            "recipes": recipes,
            "q": q,
            "page": page,
            "total": total,
            "total_pages": max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE),
            "page_size": _PAGE_SIZE,
        },
    )


# ── Детали ────────────────────────────────────────────────────────────────────


@router.get("/{recipe_id}", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def recipe_detail(request: Request, service: _ServiceDep, recipe_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        recipe = await service.get_for_admin(recipe_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return templates.TemplateResponse(
        request,
        "recipes/detail.html",
        {"admin_login": current_login(request), "recipe": recipe, "allowed_units": ALLOWED_UNITS},
    )


# ── HTMX: обновить ингредиент (qty + unit) ────────────────────────────────────


@router.post(
    "/{recipe_id}/ingredients/{ingredient_id}/update",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_update(
    request: Request,
    service: _ServiceDep,
    recipe_id: int,
    ingredient_id: int,
    quantity: str = Form(""),
    unit: str = Form(""),
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    link, ing_name = await service.update_ingredient_link(
        recipe_id, ingredient_id, quantity=parse_decimal_form(quantity), unit=unit.strip() or None
    )
    return templates.TemplateResponse(
        request,
        "recipes/partials/ingredient_row.html",
        {"link": link, "ing_name": ing_name, "recipe_id": recipe_id, "allowed_units": ALLOWED_UNITS, "editing": False},
    )


# ── HTMX: строка в режиме редактирования ─────────────────────────────────────


@router.get(
    "/{recipe_id}/ingredients/{ingredient_id}/edit-row",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_edit_row(
    request: Request, service: _ServiceDep, recipe_id: int, ingredient_id: int
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    link = await service.get_ingredient_link(recipe_id, ingredient_id, with_ingredient=True)
    if link is None:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(
        request,
        "recipes/partials/ingredient_row.html",
        {
            "link": link,
            "ing_name": link.ingredient.name,
            "recipe_id": recipe_id,
            "allowed_units": ALLOWED_UNITS,
            "editing": True,
        },
    )


# ── HTMX: удалить ингредиент ─────────────────────────────────────────────────


@router.delete(
    "/{recipe_id}/ingredients/{ingredient_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_remove(request: Request, service: _ServiceDep, recipe_id: int, ingredient_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    await service.remove_ingredient(recipe_id, ingredient_id)
    return HTMLResponse("")


# ── HTMX: добавить ингредиент ─────────────────────────────────────────────────


@router.post(
    "/{recipe_id}/ingredients/add",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_add(
    request: Request,
    service: _ServiceDep,
    recipe_id: int,
    name: str = Form(...),
    quantity: str = Form(""),
    unit: str = Form(""),
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    name = name.strip()
    if not name:
        return HTMLResponse("")
    link, ing_name = await service.add_ingredient(
        recipe_id, name, quantity=parse_decimal_form(quantity), unit=unit.strip() or None
    )
    return templates.TemplateResponse(
        request,
        "recipes/partials/ingredient_row.html",
        {"link": link, "ing_name": ing_name, "recipe_id": recipe_id, "allowed_units": ALLOWED_UNITS, "editing": False},
    )


# ── HTMX: inline-редактор title/description ──────────────────────────────────


@router.get(
    "/{recipe_id}/edit-meta",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_edit_meta_form(request: Request, service: _ServiceDep, recipe_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    recipe = await service.get_recipe_basic(recipe_id)
    if recipe is None:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "recipes/partials/meta_edit.html", {"recipe": recipe})


@router.post(
    "/{recipe_id}/edit-meta",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_save_meta(
    request: Request,
    service: _ServiceDep,
    recipe_id: int,
    title: str = Form(...),
    description: str = Form(""),
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    recipe = await service.update_meta(recipe_id, title=title.strip(), description=description.strip() or None)
    return templates.TemplateResponse(request, "recipes/partials/meta_view.html", {"recipe": recipe})


@router.get(
    "/{recipe_id}/view-meta",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_view_meta(request: Request, service: _ServiceDep, recipe_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    recipe = await service.get_recipe_basic(recipe_id)
    return templates.TemplateResponse(request, "recipes/partials/meta_view.html", {"recipe": recipe})


# ── HTMX: привязка / отвязка пользователя ────────────────────────────────────


@router.get(
    "/{recipe_id}/users/search",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_users_search(request: Request, service: _ServiceDep, recipe_id: int, q: str = "") -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    if len(q.strip()) < 2:
        return HTMLResponse("")
    users, linked_ids = await service.search_users(recipe_id, q.strip())
    return templates.TemplateResponse(
        request,
        "recipes/partials/user_search_results.html",
        {"users": users, "linked_ids": linked_ids, "recipe_id": recipe_id},
    )


@router.post(
    "/{recipe_id}/users/{user_id}/attach",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_user_attach(request: Request, service: _ServiceDep, recipe_id: int, user_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    user = await service.attach_user(recipe_id, user_id)
    return templates.TemplateResponse(
        request,
        "recipes/partials/linked_user_chip.html",
        {"user": user, "recipe_id": recipe_id},
    )


@router.delete(
    "/{recipe_id}/users/{user_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_user_detach(request: Request, service: _ServiceDep, recipe_id: int, user_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    await service.detach_user(recipe_id, user_id)
    return HTMLResponse("")


# ── Удаление рецепта ─────────────────────────────────────────────────────────


@router.delete("/{recipe_id}", response_model=None, include_in_schema=False)
async def recipe_delete(request: Request, service: _ServiceDep, recipe_id: int) -> RedirectResponse | HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)
    await service.delete(recipe_id)
    return RedirectResponse(url="/admin/recipes", status_code=303)
