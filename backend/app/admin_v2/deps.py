"""Зависимости для admin_v2 роутов."""

from fastapi import Request
from fastapi.responses import RedirectResponse

from backend.app.utils.fastapi_state import get_backend_db, get_backend_redis
from packages.db.database import Database

_LOGIN_URL = "/admin_v2/login"


def get_db(request: Request) -> Database:
    return get_backend_db(request)


def get_redis(request: Request):
    return get_backend_redis(request)


def check_auth(request: Request) -> RedirectResponse | None:
    """Возвращает редирект на login если не залогинен, иначе None."""
    if "admin_login" not in request.session:
        return RedirectResponse(url=_LOGIN_URL, status_code=303)
    return None


def current_login(request: Request) -> str:
    return str(request.session.get("admin_login", ""))
