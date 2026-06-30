import logging

from fastapi import FastAPI

from backend.app.core import (
    setup_exception_handlers,
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
    setup_routes(app)

    setup_exception_handlers(app)

    return app


app = create_app()
