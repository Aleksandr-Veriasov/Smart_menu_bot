import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqladmin import Admin
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.routing import Mount

from backend.app.admin.views import AdminAuth, setup_admin
from backend.app.core import setup_middleware, setup_routes, setup_static
from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.db.migrate_and_seed import ensure_admin
from packages.logging_config import setup_logging
from packages.redis.redis_conn import close_redis, get_redis

setup_logging()
logger = logging.getLogger(__name__)


def _propagate_state_to_mounted_apps(app: FastAPI, *, state: AppState) -> None:
    """
    SQLAdmin монтируется как sub-app. Для таких sub-app `request.app.state.*` не совпадает с корневым FastAPI app.state.
    Поэтому дублируем ссылки на общие ресурсы (db/redis/app_state) во все mounted приложения.
    """

    for route in getattr(app, "routes", []) or []:
        if not isinstance(route, Mount):
            continue
        try:
            sub_app = route.app
        except Exception:
            continue
        if sub_app is None:
            continue
        # StaticFiles и некоторые другие ASGI apps не имеют .state
        if not hasattr(sub_app, "state"):
            continue
        # Делаем те же поля, что и на root app, чтобы хелперы вида get_backend_redis() работали везде.
        sub_app.state.app_state = state
        sub_app.state.db = state.db
        sub_app.state.redis = getattr(state, "redis", None)


def create_app() -> FastAPI:
    # Create long-lived resources once; lifespan is only for connect/disconnect.
    state = AppState(
        db=Database(
            db_url=settings.db.sqlalchemy_url(use_async=True),
            echo=settings.debug,
            pool_recycle=settings.db.pool_recycle,
            pool_pre_ping=settings.db.pool_pre_ping,
        ),
        cleanup_task=None,
    )
    engine: AsyncEngine = state.db.engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Делаем ресурсы доступными из роутеров через request.app.state.*
        app.state.app_state = state
        app.state.db = state.db
        app.state.redis = None
        _propagate_state_to_mounted_apps(app, state=state)

        # Redis
        state.redis = await get_redis()
        app.state.redis = state.redis
        _propagate_state_to_mounted_apps(app, state=state)
        ping = await state.redis.ping()
        logger.info(f"🧠 Redis подключён PING={ping}")

        logger.info("БД загружена")
        await ensure_admin(state.db)

        try:
            yield
        finally:
            # Закрываем Redis первым
            if state.redis is not None:
                await close_redis()
                state.redis = None
                app.state.redis = None
                _propagate_state_to_mounted_apps(app, state=state)
                logger.info("🔒 Redis закрыт.")
            await engine.dispose()

    app = FastAPI(
        title="Recipes Backend",
        debug=settings.debug,
        lifespan=lifespan,
    )

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    setup_static(app)
    setup_middleware(app)

    # SQLAdmin c auth: register routes at app creation time, not inside lifespan.
    pepper = settings.security.password_pepper
    if pepper is None:
        raise RuntimeError("PASSWORD_PEPPER не задан: SessionMiddleware/AdminAuth не может стартовать.")
    authentication_backend = AdminAuth(state.db, secret_key=pepper.get_secret_value())
    admin = Admin(
        app,
        engine,
        authentication_backend=authentication_backend,
        templates_dir="backend/web/templates",
    )
    setup_admin(admin)
    logger.info("Админка загружена")

    setup_routes(app)

    return app


app = create_app()
