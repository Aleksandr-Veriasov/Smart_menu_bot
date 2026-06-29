from fastapi import FastAPI

from backend.app.api.webapp import webapp_router


def setup_routes(app: FastAPI) -> None:
    app.include_router(webapp_router, prefix="/api/webapp", tags=["webapp"])
