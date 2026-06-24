from fastapi import FastAPI

from backend.app.api.routers import api_router
from backend.app.broadcast.page import broadcast_page_router


def setup_routes(app: FastAPI) -> None:
    app.include_router(api_router, prefix="/api")
    app.include_router(broadcast_page_router)
