"""admin: список, детали и inline-редактор ингредиентов рецептов."""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import joinedload

from backend.app.admin.deps import check_auth, current_login
from backend.app.admin.templates import templates
from backend.app.utils.fastapi_state import get_backend_db
from packages.db.models import Recipe, RecipeIngredient, RecipeUser
from packages.db.models.recipe import Ingredient
from packages.db.models.user import User
from packages.db.repository.ingredient import IngredientRepository
from packages.db.repository.recipe_ingredient import (
    IngredientLink,
    RecipeIngredientRepository,
)
from packages.recipes_core.units import ALLOWED_UNITS

router = APIRouter()

_PAGE_SIZE = 25


# ── Список ────────────────────────────────────────────────────────────────────


@router.get("/recipes", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def recipes_list(request: Request, page: int = 1, q: str = "") -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    offset = (page - 1) * _PAGE_SIZE

    async with db.session() as session:
        base = select(Recipe)
        if q:
            base = base.where(Recipe.title.ilike(f"%{q}%"))

        total: int = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

        stmt = (
            base.options(joinedload(Recipe.ingredients), joinedload(Recipe.linked_users), joinedload(Recipe.video))
            .order_by(Recipe.id.desc())
            .offset(offset)
            .limit(_PAGE_SIZE)
        )
        recipes = (await session.execute(stmt)).unique().scalars().all()

    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    return templates.TemplateResponse(
        request,
        "recipes/list.html",
        {
            "admin_login": current_login(request),
            "recipes": recipes,
            "q": q,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "page_size": _PAGE_SIZE,
        },
    )


# ── Детали ────────────────────────────────────────────────────────────────────


async def _load_recipe(session, recipe_id: int) -> Recipe | None:
    stmt = (
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .options(
            joinedload(Recipe.ingredient_links).joinedload(RecipeIngredient.ingredient),
            joinedload(Recipe.linked_users),
            joinedload(Recipe.video),
            joinedload(Recipe.recipe_users).joinedload(RecipeUser.category),
        )
    )
    return (await session.execute(stmt)).unique().scalar_one_or_none()


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def recipe_detail(request: Request, recipe_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        recipe = await _load_recipe(session, recipe_id)

    if recipe is None:
        return RedirectResponse(url="/admin/recipes", status_code=303)

    return templates.TemplateResponse(
        request,
        "recipes/detail.html",
        {
            "admin_login": current_login(request),
            "recipe": recipe,
            "allowed_units": ALLOWED_UNITS,
        },
    )


# ── HTMX: обновить ингредиент (qty + unit) ────────────────────────────────────


@router.post(
    "/recipes/{recipe_id}/ingredients/{ingredient_id}/update",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_update(
    request: Request,
    recipe_id: int,
    ingredient_id: int,
    quantity: str = Form(""),
    unit: str = Form(""),
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    qty: Decimal | None = None
    if quantity.strip():
        try:
            qty = Decimal(quantity.strip())
        except InvalidOperation:
            pass

    unit_val = unit.strip() or None

    db = get_backend_db(request)
    async with db.session() as session:
        link = await session.scalar(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe_id,
                RecipeIngredient.ingredient_id == ingredient_id,
            )
        )
        if link:
            link.quantity = qty
            link.unit = unit_val
            ing_name = (await session.get(Ingredient, ingredient_id)).name
        else:
            ing_name = "?"

    return templates.TemplateResponse(
        request,
        "recipes/partials/ingredient_row.html",
        {
            "link": link,
            "ing_name": ing_name,
            "recipe_id": recipe_id,
            "allowed_units": ALLOWED_UNITS,
            "editing": False,
        },
    )


# ── HTMX: получить строку в режиме редактирования ────────────────────────────


@router.get(
    "/recipes/{recipe_id}/ingredients/{ingredient_id}/edit-row",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_edit_row(
    request: Request,
    recipe_id: int,
    ingredient_id: int,
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    db = get_backend_db(request)
    async with db.session() as session:
        link = await session.scalar(
            select(RecipeIngredient)
            .where(
                RecipeIngredient.recipe_id == recipe_id,
                RecipeIngredient.ingredient_id == ingredient_id,
            )
            .options(joinedload(RecipeIngredient.ingredient))
        )

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
    "/recipes/{recipe_id}/ingredients/{ingredient_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_remove(
    request: Request,
    recipe_id: int,
    ingredient_id: int,
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    db = get_backend_db(request)
    async with db.session() as session:
        await session.execute(
            delete(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe_id,
                RecipeIngredient.ingredient_id == ingredient_id,
            )
        )

    return HTMLResponse("")  # HTMX удаляет строку из DOM


# ── HTMX: добавить ингредиент ─────────────────────────────────────────────────


@router.post(
    "/recipes/{recipe_id}/ingredients/add",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def ingredient_add(
    request: Request,
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

    qty: Decimal | None = None
    if quantity.strip():
        try:
            qty = Decimal(quantity.strip())
        except InvalidOperation:
            pass
    unit_val = unit.strip() or None

    db = get_backend_db(request)
    async with db.session() as session:
        id_by_name = await IngredientRepository(session).bulk_get_or_create([name])
        ing_id = id_by_name[name]
        await RecipeIngredientRepository(session).bulk_link(
            recipe_id, [IngredientLink(ingredient_id=ing_id, quantity=qty, unit=unit_val)]
        )
        link = await session.scalar(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe_id,
                RecipeIngredient.ingredient_id == ing_id,
            )
        )

    return templates.TemplateResponse(
        request,
        "recipes/partials/ingredient_row.html",
        {
            "link": link,
            "ing_name": name,
            "recipe_id": recipe_id,
            "allowed_units": ALLOWED_UNITS,
            "editing": False,
        },
    )


# ── ADM-16: HTMX inline-редактор title/description ───────────────────────────


@router.get(
    "/recipes/{recipe_id}/edit-meta",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_edit_meta_form(request: Request, recipe_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    db = get_backend_db(request)
    async with db.session() as session:
        recipe = await session.get(Recipe, recipe_id)

    if recipe is None:
        return HTMLResponse("", status_code=404)

    return templates.TemplateResponse(
        request,
        "recipes/partials/meta_edit.html",
        {
            "recipe": recipe,
        },
    )


@router.post(
    "/recipes/{recipe_id}/edit-meta",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_save_meta(
    request: Request,
    recipe_id: int,
    title: str = Form(...),
    description: str = Form(""),
) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    title = title.strip()
    desc: str | None = description.strip() or None

    db = get_backend_db(request)
    async with db.session() as session:
        await session.execute(update(Recipe).where(Recipe.id == recipe_id).values(title=title, description=desc))
        recipe = await session.get(Recipe, recipe_id)

    return templates.TemplateResponse(
        request,
        "recipes/partials/meta_view.html",
        {
            "recipe": recipe,
        },
    )


@router.get(
    "/recipes/{recipe_id}/view-meta",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_view_meta(request: Request, recipe_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    db = get_backend_db(request)
    async with db.session() as session:
        recipe = await session.get(Recipe, recipe_id)

    return templates.TemplateResponse(
        request,
        "recipes/partials/meta_view.html",
        {
            "recipe": recipe,
        },
    )


# ── ADM-17: привязка / отвязка пользователя ──────────────────────────────────


@router.get(
    "/recipes/{recipe_id}/users/search",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_users_search(request: Request, recipe_id: int, q: str = "") -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    if len(q.strip()) < 2:
        return HTMLResponse("")

    db = get_backend_db(request)
    async with db.session() as session:
        linked_ids = set(
            (await session.execute(select(RecipeUser.user_id).where(RecipeUser.recipe_id == recipe_id))).scalars().all()
        )

        stmt = select(User).where(User.username.ilike(f"%{q.strip()}%")).limit(10)
        users = (await session.execute(stmt)).scalars().all()

    return templates.TemplateResponse(
        request,
        "recipes/partials/user_search_results.html",
        {
            "users": users,
            "linked_ids": linked_ids,
            "recipe_id": recipe_id,
        },
    )


@router.post(
    "/recipes/{recipe_id}/users/{user_id}/attach",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_user_attach(request: Request, recipe_id: int, user_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    db = get_backend_db(request)
    async with db.session() as session:
        exists = await session.scalar(
            select(RecipeUser).where(
                RecipeUser.recipe_id == recipe_id,
                RecipeUser.user_id == user_id,
            )
        )
        if not exists:
            session.add(RecipeUser(recipe_id=recipe_id, user_id=user_id))
        user = await session.get(User, user_id)

    return templates.TemplateResponse(
        request,
        "recipes/partials/linked_user_chip.html",
        {
            "user": user,
            "recipe_id": recipe_id,
        },
    )


@router.delete(
    "/recipes/{recipe_id}/users/{user_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def recipe_user_detach(request: Request, recipe_id: int, user_id: int) -> HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    db = get_backend_db(request)
    async with db.session() as session:
        await session.execute(
            delete(RecipeUser).where(
                RecipeUser.recipe_id == recipe_id,
                RecipeUser.user_id == user_id,
            )
        )

    return HTMLResponse("")  # HTMX удаляет чип из DOM


# ── ADM-18: удаление рецепта ──────────────────────────────────────────────────


@router.delete(
    "/recipes/{recipe_id}",
    response_model=None,
    include_in_schema=False,
)
async def recipe_delete(request: Request, recipe_id: int) -> RedirectResponse | HTMLResponse:
    if "admin_login" not in request.session:
        return HTMLResponse("Unauthorized", status_code=401)

    db = get_backend_db(request)
    async with db.session() as session:
        recipe = await session.get(Recipe, recipe_id)
        if recipe:
            await session.delete(recipe)

    return RedirectResponse(url="/admin/recipes", status_code=303)
