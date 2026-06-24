from fastapi import Header, HTTPException, Request

from backend.app.api.webapp.tg_webapp_auth import validate_telegram_webapp_init_data
from backend.app.utils.fastapi_state import (
    get_backend_db,
    get_backend_redis,
    get_backend_redis_optional,
)
from packages.common_settings.settings import settings
from packages.services import AdminService, BroadcastService, WebAppService


def require_admin(request: Request) -> None:
    if "admin_login" not in request.session:
        raise HTTPException(status_code=401, detail="Not authenticated")


def get_admin_service(request: Request) -> AdminService:
    return AdminService(get_backend_db(request), get_backend_redis(request))


def get_broadcast_service(request: Request) -> BroadcastService:
    return BroadcastService(get_backend_db(request), get_backend_redis(request))


def get_webapp_service(request: Request) -> WebAppService:
    return WebAppService(get_backend_db(request), get_backend_redis_optional(request))


def get_tg_user_id(x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA")) -> int:
    init_data = (x_tg_init_data or "").strip()
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствует заголовок X-TG-INIT-DATA")
    token = settings.telegram.bot_token.get_secret_value().strip()
    user = validate_telegram_webapp_init_data(init_data, bot_token=token)
    return int(user.id)
