"""admin: список, создание, редактирование и удаление ингредиентов."""

from fastapi import APIRouter, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from backend.app.admin.deps import check_auth, current_login
from backend.app.admin.templates import templates
from backend.app.utils.fastapi_state import get_backend_db
from packages.db.models.recipe import Ingredient

router = APIRouter()

_PAGE_SIZE = 30


@router.get("/ingredients", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def ingredients_list(request: Request, page: int = 1, q: str = "") -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    offset = (page - 1) * _PAGE_SIZE

    async with db.session() as session:
        base = select(Ingredient)
        if q:
            base = base.where(Ingredient.name.ilike(f"%{q}%"))

        total: int = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

        stmt = base.options(joinedload(Ingredient.recipes)).order_by(Ingredient.name).offset(offset).limit(_PAGE_SIZE)
        result = await session.execute(stmt)
        ingredients = result.unique().scalars().all()

    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    return templates.TemplateResponse(
        request,
        "ingredients/list.html",
        {
            "admin_login": current_login(request),
            "ingredients": ingredients,
            "q": q,
            "page": page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/ingredients/new", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def ingredient_new_form(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "ingredients/form.html",
        {
            "admin_login": current_login(request),
            "ingredient": None,
            "error": None,
        },
    )


@router.post("/ingredients/new", response_model=None, include_in_schema=False)
async def ingredient_create(
    request: Request,
    name: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect

    name = name.strip()
    if not name:
        return templates.TemplateResponse(
            request,
            "ingredients/form.html",
            {
                "admin_login": current_login(request),
                "ingredient": None,
                "error": "Название обязательно",
            },
        )

    db = get_backend_db(request)
    async with db.session() as session:
        existing = await session.scalar(select(Ingredient).where(Ingredient.name == name))
        if existing:
            return templates.TemplateResponse(
                request,
                "ingredients/form.html",
                {
                    "admin_login": current_login(request),
                    "ingredient": None,
                    "error": f"Ингредиент «{name}» уже существует",
                },
            )
        session.add(Ingredient(name=name))

    return RedirectResponse(url="/admin/ingredients", status_code=303)


@router.get("/ingredients/{ing_id}/edit", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def ingredient_edit_form(request: Request, ing_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        ing = await session.get(Ingredient, ing_id)

    if ing is None:
        raise HTTPException(status_code=404, detail=f"Ингредиент #{ing_id} не найден")

    return templates.TemplateResponse(
        request,
        "ingredients/form.html",
        {
            "admin_login": current_login(request),
            "ingredient": ing,
            "error": None,
        },
    )


@router.post("/ingredients/{ing_id}/edit", response_model=None, include_in_schema=False)
async def ingredient_update(
    request: Request,
    ing_id: int,
    name: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect

    name = name.strip()
    if not name:
        db = get_backend_db(request)
        async with db.session() as session:
            ing = await session.get(Ingredient, ing_id)
        return templates.TemplateResponse(
            request,
            "ingredients/form.html",
            {
                "admin_login": current_login(request),
                "ingredient": ing,
                "error": "Название обязательно",
            },
        )

    db = get_backend_db(request)
    async with db.session() as session:
        ing = await session.get(Ingredient, ing_id)
        if ing is None:
            raise HTTPException(status_code=404, detail=f"Ингредиент #{ing_id} не найден")
        existing = await session.scalar(select(Ingredient).where(Ingredient.name == name, Ingredient.id != ing_id))
        if existing:
            return templates.TemplateResponse(
                request,
                "ingredients/form.html",
                {
                    "admin_login": current_login(request),
                    "ingredient": ing,
                    "error": f"Ингредиент «{name}» уже существует",
                },
            )
        ing.name = name

    return RedirectResponse(url="/admin/ingredients", status_code=303)


@router.post("/ingredients/{ing_id}/delete", response_model=None, include_in_schema=False)
async def ingredient_delete(request: Request, ing_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        ing = await session.get(Ingredient, ing_id)
        if ing:
            await session.delete(ing)

    return RedirectResponse(url="/admin/ingredients", status_code=303)
