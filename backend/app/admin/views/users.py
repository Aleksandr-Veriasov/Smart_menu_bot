"""admin: список и детали пользователей."""

from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from backend.app.admin.deps import check_auth, current_login
from backend.app.admin.templates import templates
from backend.app.utils.fastapi_state import get_backend_db
from packages.db.models import User
from packages.db.models.recipe import Recipe

router = APIRouter()

_PAGE_SIZE = 25


@router.get("/users", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def users_list(request: Request, page: int = 1, q: str = "") -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    offset = (page - 1) * _PAGE_SIZE

    async with db.session() as session:
        base = select(User)
        if q:
            base = base.where(User.username.ilike(f"%{q}%") | User.first_name.ilike(f"%{q}%"))

        total: int = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

        stmt = base.options(joinedload(User.linked_recipes)).order_by(User.id.desc()).offset(offset).limit(_PAGE_SIZE)
        result = await session.execute(stmt)
        users = result.unique().scalars().all()

    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    return templates.TemplateResponse(
        request,
        "users/list.html",
        {
            "admin_login": current_login(request),
            "users": users,
            "q": q,
            "page": page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/users/{user_id}", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def user_detail(request: Request, user_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)

    async with db.session() as session:
        stmt = select(User).where(User.id == user_id).options(joinedload(User.linked_recipes).joinedload(Recipe.video))
        result = await session.execute(stmt)
        user = result.unique().scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail=f"Пользователь #{user_id} не найден")

    return templates.TemplateResponse(
        request,
        "users/detail.html",
        {
            "admin_login": current_login(request),
            "user": user,
        },
    )
