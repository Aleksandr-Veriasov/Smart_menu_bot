"""admin: список и детали пользователей."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_user_service
from backend.app.core.templates import templates
from packages.services.user_service import UserService

router = APIRouter(prefix="/users")

_PAGE_SIZE = 25
_ServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.get("", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def users_list(
    request: Request, service: _ServiceDep, page: int = 1, q: str = ""
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    users, total = await service.list_page(page, _PAGE_SIZE, q)
    return templates.TemplateResponse(
        request,
        "users/list.html",
        {
            "admin_login": current_login(request),
            "users": users,
            "q": q,
            "page": page,
            "total": total,
            "total_pages": max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE),
        },
    )


@router.get("/{user_id}", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def user_detail(request: Request, service: _ServiceDep, user_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    try:
        user = await service.get_or_raise(user_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None

    return templates.TemplateResponse(
        request,
        "users/detail.html",
        {"admin_login": current_login(request), "user": user},
    )
