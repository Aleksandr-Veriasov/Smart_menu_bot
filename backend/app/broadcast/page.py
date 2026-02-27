from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from starlette.responses import FileResponse, RedirectResponse, Response


def setup_broadcast_page(app: FastAPI) -> None:
    @app.get("/broadcast", include_in_schema=False)
    async def broadcast_page(request: Request) -> Response:
        # Reuse SQLAdmin session auth.
        if "admin_login" not in request.session:
            return RedirectResponse(url="/admin/login", status_code=303)

        path = Path("backend/web/broadcast/index.html")
        if not path.exists():
            # Keep error explicit; easier to diagnose in logs.
            raise RuntimeError("Broadcast UI file missing: backend/web/broadcast/index.html")
        return FileResponse(path)
