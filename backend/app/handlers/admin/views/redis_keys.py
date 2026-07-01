"""admin: просмотр Redis-ключей с HTMX-обновлением."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_admin_service
from backend.app.core.templates import templates
from packages.services.admin_service import AdminService

router = APIRouter(prefix="/redis-keys")

_PER_PAGE = 100
_ServiceDep = Annotated[AdminService, Depends(get_admin_service)]


def _fmt_ttl(v: int) -> str:
    if v == -1:
        return "∞"
    if v == -2:
        return "gone"
    return f"{v // 60}m {v % 60}s"


@router.get("", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def redis_keys_list(request: Request, service: _ServiceDep, page: int = 1) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    key_ttls, total_keys, has_more = await service.list_redis_keys_page(page, _PER_PAGE)
    rows = [{"key": k, "ttl": _fmt_ttl(t)} for k, t in key_ttls]

    return templates.TemplateResponse(
        request,
        "redis/list.html",
        {
            "admin_login": current_login(request),
            "rows": rows,
            "total_keys": total_keys,
            "page": page,
            "per_page": _PER_PAGE,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if has_more else None,
        },
    )


@router.get("/value", response_class=JSONResponse, include_in_schema=False)
async def redis_key_value(request: Request, service: _ServiceDep, key: str = "") -> JSONResponse:
    if "admin_login" not in request.session:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not key:
        return JSONResponse({"error": "no key"}, status_code=400)

    missing, value = await service.get_redis_key_value(key)
    return JSONResponse({"missing": missing, "value": value})


@router.post("/delete", response_model=None, include_in_schema=False)
async def redis_key_delete(
    request: Request,
    service: _ServiceDep,
    key: str = Form(""),
    page: str = Form("1"),
) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    if key:
        await service.delete_redis_key(key)

    return RedirectResponse(url=f"/admin/redis-keys?page={page}", status_code=303)
