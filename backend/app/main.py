import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.app.admin_v2.router import router as admin_v2_router
from backend.app.core import (
    setup_middleware,
    setup_observability,
    setup_routes,
    setup_static,
)
from backend.app.lifespan import build_lifespan
from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    state = AppState(
        db=Database(
            db_url=settings.db.sqlalchemy_url(use_async=True),
            echo=settings.debug,
            pool_recycle=settings.db.pool_recycle,
            pool_pre_ping=settings.db.pool_pre_ping,
            pool_size=3,
            max_overflow=3,
        ),
        cleanup_task=None,
    )

    app = FastAPI(
        title="Recipes Backend",
        debug=settings.debug,
        lifespan=build_lifespan(state),
    )

    setup_observability(app)
    setup_static(app)
    setup_middleware(app)
    app.include_router(admin_v2_router)
    setup_routes(app)

    @app.exception_handler(LookupError)
    async def lookup_error_handler(_: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    return app


app = create_app()
