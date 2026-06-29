"""admin: CRUD категорий с инвалидацией Redis-кэша."""

from fastapi import APIRouter, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from backend.app.admin.deps import check_auth, current_login
from backend.app.admin.templates import templates
from backend.app.utils.fastapi_state import get_backend_db, get_backend_redis
from packages.db.models.recipe import Category
from packages.redis.repository.category import CategoryCacheRepository

router = APIRouter()


async def _invalidate(redis) -> None:
    await CategoryCacheRepository(redis).invalidate_all_name_and_slug()


# ── Список ────────────────────────────────────────────────────────────────────


@router.get("/categories", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def categories_list(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        result = await session.execute(select(Category).order_by(Category.id))
        categories = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "categories/list.html",
        {
            "admin_login": current_login(request),
            "categories": categories,
        },
    )


# ── Создание ──────────────────────────────────────────────────────────────────


@router.get("/categories/new", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def category_new_form(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "categories/form.html",
        {
            "admin_login": current_login(request),
            "category": None,
            "error": None,
        },
    )


@router.post("/categories/new", response_model=None, include_in_schema=False)
async def category_create(
    request: Request,
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
            {
                "admin_login": current_login(request),
                "category": None,
                "error": "Название обязательно",
            },
        )

    db = get_backend_db(request)
    async with db.session() as session:
        cat = Category(name=name, slug=slug_val)
        session.add(cat)
        await session.flush()
    redis = get_backend_redis(request)
    await _invalidate(redis)
    return RedirectResponse(url="/admin/categories", status_code=303)


# ── Редактирование ────────────────────────────────────────────────────────────


@router.get("/categories/{cat_id}/edit", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def category_edit_form(request: Request, cat_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        cat = await session.get(Category, cat_id)

    if cat is None:
        raise HTTPException(status_code=404, detail=f"Категория #{cat_id} не найдена")

    return templates.TemplateResponse(
        request,
        "categories/form.html",
        {
            "admin_login": current_login(request),
            "category": cat,
            "error": None,
        },
    )


@router.post("/categories/{cat_id}/edit", response_model=None, include_in_schema=False)
async def category_update(
    request: Request,
    cat_id: int,
    name: str = Form(...),
    slug: str = Form(""),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect

    name, slug_val = name.strip(), slug.strip() or None

    if not name:
        db = get_backend_db(request)
        async with db.session() as session:
            cat = await session.get(Category, cat_id)
        return templates.TemplateResponse(
            request,
            "categories/form.html",
            {
                "admin_login": current_login(request),
                "category": cat,
                "error": "Название обязательно",
            },
        )

    db = get_backend_db(request)
    async with db.session() as session:
        cat = await session.get(Category, cat_id)
        if cat is None:
            raise HTTPException(status_code=404, detail=f"Категория #{cat_id} не найдена")
        cat.name = name
        cat.slug = slug_val

    redis = get_backend_redis(request)
    await _invalidate(redis)
    return RedirectResponse(url="/admin/categories", status_code=303)


# ── Удаление ──────────────────────────────────────────────────────────────────


@router.post("/categories/{cat_id}/delete", response_model=None, include_in_schema=False)
async def category_delete(request: Request, cat_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    deleted = False
    async with db.session() as session:
        cat = await session.get(Category, cat_id)
        if cat:
            await session.delete(cat)
            deleted = True

    if deleted:
        redis = get_backend_redis(request)
        await _invalidate(redis)

    return RedirectResponse(url="/admin/categories", status_code=303)
