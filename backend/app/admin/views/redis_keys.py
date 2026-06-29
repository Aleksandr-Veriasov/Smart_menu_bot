"""admin: просмотр Redis-ключей с HTMX-обновлением."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.app.admin.deps import check_auth, current_login
from backend.app.admin.templates import templates
from backend.app.utils.fastapi_state import get_backend_redis

router = APIRouter()

_PER_PAGE = 100


@router.get("/redis-keys", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def redis_keys_list(request: Request, page: int = 1) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    redis = get_backend_redis(request)
    per_page = _PER_PAGE
    start = (page - 1) * per_page

    cursor = 0
    skipped = 0
    collected: list[bytes] = []
    has_more = False

    while True:
        cursor, keys = await redis.scan(cursor=cursor, count=per_page)
        if keys:
            if skipped < start:
                if skipped + len(keys) <= start:
                    skipped += len(keys)
                    keys = []
                else:
                    keys = keys[start - skipped :]
                    skipped = start
            if keys:
                needed = per_page - len(collected)
                collected.extend(keys[:needed])
                if len(keys) > needed:
                    has_more = True
                    break
        if cursor == 0:
            break
        if len(collected) >= per_page:
            has_more = True
            break

    key_names = sorted(
        k.decode("utf-8", errors="replace") if isinstance(k, bytes | bytearray) else str(k) for k in collected
    )
    total_keys = await redis.dbsize()

    ttls: list[int] = []
    if key_names:
        pipe = redis.pipeline()
        for k in key_names:
            pipe.ttl(k)
        ttls = await pipe.execute()

    def _fmt_ttl(v: int) -> str:
        if v == -1:
            return "∞"
        if v == -2:
            return "gone"
        return f"{v // 60}m {v % 60}s"

    rows = [{"key": k, "ttl": _fmt_ttl(t)} for k, t in zip(key_names, ttls, strict=False)]

    return templates.TemplateResponse(
        request,
        "redis/list.html",
        {
            "admin_login": current_login(request),
            "rows": rows,
            "total_keys": total_keys,
            "page": page,
            "per_page": per_page,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if has_more else None,
        },
    )


@router.get("/redis-keys/value", response_class=JSONResponse, include_in_schema=False)
async def redis_key_value(request: Request, key: str = "") -> JSONResponse:
    if "admin_login" not in request.session:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not key:
        return JSONResponse({"error": "no key"}, status_code=400)

    redis = get_backend_redis(request)
    raw = await redis.get(key)
    if raw is None:
        return JSONResponse({"missing": True, "value": ""})
    value = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes | bytearray) else str(raw)
    return JSONResponse({"missing": False, "value": value})


@router.post("/redis-keys/delete", response_model=None, include_in_schema=False)
async def redis_key_delete(
    request: Request,
    key: str = Form(""),
    page: str = Form("1"),
) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    if key:
        redis = get_backend_redis(request)
        await redis.delete(key)

    return RedirectResponse(url=f"/admin/redis-keys?page={page}", status_code=303)
