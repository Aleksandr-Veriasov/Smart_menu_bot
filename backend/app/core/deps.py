from fastapi import Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis

from packages.app_state import AppState
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.services import BroadcastService, WebAppService
from packages.services.admin_service import AdminService
from packages.services.category_service import CategoryService
from packages.services.ingredient_service import IngredientService
from packages.services.recipe_service import RecipeService
from packages.services.user_service import UserService

_ADMIN_LOGIN_URL = "/admin/login"


def get_app_state(request: Request) -> AppState:
    """Единая точка доступа к AppState из FastAPI app.state."""
    app_state = getattr(request.app.state, "app_state", None)
    if app_state is None:
        raise HTTPException(status_code=500, detail="AppState не настроен")
    return app_state


def get_backend_db(request: Request) -> Database:
    """Достаёт Database из AppState."""
    return get_app_state(request).db


def get_backend_redis(request: Request) -> Redis:
    """Достаёт Redis из AppState; бросает 503 если Redis недоступен."""
    redis = get_app_state(request).redis
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis недоступен")
    return redis


def get_backend_redis_optional(request: Request) -> Redis | None:
    """Достаёт Redis из AppState без ошибки если недоступен (best-effort)."""
    return get_app_state(request).redis


def require_admin(request: Request) -> None:
    """Защита JSON API — бросает 401 если нет сессии."""
    if "admin_login" not in request.session:
        raise HTTPException(status_code=401, detail="Not authenticated")


def check_auth(request: Request) -> RedirectResponse | None:
    """Защита HTML-вьюх — редирект на login если нет сессии."""
    if "admin_login" not in request.session:
        return RedirectResponse(url=_ADMIN_LOGIN_URL, status_code=303)
    return None


def current_login(request: Request) -> str:
    """Вернуть логин текущего администратора из сессии."""
    return str(request.session.get("admin_login", ""))


def get_admin_service(request: Request) -> AdminService:
    return AdminService(get_backend_db(request), get_backend_redis(request))


def get_broadcast_service(request: Request) -> BroadcastService:
    return BroadcastService(get_backend_db(request), get_backend_redis(request))


def get_category_service(request: Request) -> CategoryService:
    return CategoryService(get_backend_db(request), get_backend_redis(request))


def get_ingredient_service(request: Request) -> IngredientService:
    return IngredientService(get_backend_db(request), get_backend_redis_optional(request))


def get_recipe_service(request: Request) -> RecipeService:
    return RecipeService(get_backend_db(request), get_backend_redis_optional(request))


def get_user_service(request: Request) -> UserService:
    return UserService(get_backend_db(request), get_backend_redis_optional(request))


def get_webapp_service(request: Request) -> WebAppService:
    return WebAppService(get_backend_db(request), get_backend_redis_optional(request))


def get_tg_user_id(x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA")) -> int:
    from backend.app.security.tg_webapp_auth import validate_telegram_webapp_init_data

    init_data = (x_tg_init_data or "").strip()
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствует заголовок X-TG-INIT-DATA")
    token = settings.telegram.bot_token.get_secret_value().strip()
    user = validate_telegram_webapp_init_data(init_data, bot_token=token)
    return int(user.id)
