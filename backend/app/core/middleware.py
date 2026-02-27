from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from packages.common_settings.settings import settings


def setup_middleware(app: FastAPI) -> None:
    # Trusted hosts
    allowed = settings.fast_api.allowed_hosts
    if settings.debug and allowed:
        # In debug allow '*' to avoid host-header issues in tunnels/proxies.
        allowed = allowed + ["*"]
    if allowed:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)

    # Session cookie for SQLAdmin auth
    pepper = settings.security.password_pepper
    if pepper is None:
        raise RuntimeError("PASSWORD_PEPPER не задан: SessionMiddleware/AdminAuth не может стартовать.")
    app.add_middleware(SessionMiddleware, secret_key=pepper.get_secret_value())

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
