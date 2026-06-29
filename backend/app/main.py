import logging

from fastapi import FastAPI
from fastapi.exceptions import HTTPException

from backend.app.admin.router import router as admin_router
from backend.app.core import (
    setup_middleware,
    setup_observability,
    setup_routes,
    setup_static,
)
from backend.app.exception_handlers import (
    http_exception_handler,
    internal_error_handler,
    lookup_error_handler,
    value_error_handler,
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
    app.include_router(admin_router)
    setup_routes(app)

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(LookupError, lookup_error_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)

    return app


app = create_app()
