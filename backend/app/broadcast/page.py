from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from starlette.responses import FileResponse, RedirectResponse, Response

broadcast_page_router = APIRouter()


@broadcast_page_router.get("/broadcast", include_in_schema=False)
async def broadcast_page(request: Request) -> Response:
    if "admin_login" not in request.session:
        return RedirectResponse(url="/admin/login", status_code=303)

    path = Path("backend/web/broadcast/index.html")
    if not path.exists():
        raise RuntimeError("Broadcast UI file missing: backend/web/broadcast/index.html")
    return FileResponse(path)
