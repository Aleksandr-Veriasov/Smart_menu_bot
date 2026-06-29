from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.admin_v2.auth import authenticate
from backend.app.admin_v2.templates import templates
from backend.app.utils.fastapi_state import get_backend_db

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
    db = get_backend_db(request)
    ok = await authenticate(username, password, db)
    if ok:
        request.session["admin_login"] = username
        return RedirectResponse(url="/admin_v2/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": "Неверный логин или пароль"})


@router.get("/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin_v2/login", status_code=303)
