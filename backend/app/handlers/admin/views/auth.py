from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import get_backend_db, get_backend_redis
from backend.app.core.templates import templates
from packages.services import AdminService

router = APIRouter()


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_model=None, include_in_schema=False)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    ok = await AdminService(get_backend_db(request), get_backend_redis(request)).authenticate(username, password)
    if ok:
        request.session["admin_login"] = username
        return RedirectResponse(url="/admin/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": "Неверный логин или пароль"})


@router.get("/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)
