from fastapi import FastAPI

from backend.app.api.webapp import router as webapp_router
from backend.app.handlers.admin.router import router as admin_router
from backend.app.handlers.health import router as health_router


def setup_routes(app: FastAPI) -> None:
    app.include_router(admin_router)
    app.include_router(webapp_router)
    app.include_router(health_router)
