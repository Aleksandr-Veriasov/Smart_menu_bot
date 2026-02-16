from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from packages.common_settings.settings import settings


def setup_static(app: FastAPI) -> None:
    # Optional app-served static/media (depends on serve_from_app)
    if settings.fast_api.serve_from_app:
        app.mount(
            settings.fast_api.mount_static_url,
            StaticFiles(directory=settings.fast_api.static_dir, html=False),
            name="static",
        )
        app.mount(
            settings.fast_api.mount_media_url,
            StaticFiles(directory=settings.fast_api.media_dir, html=False),
            name="media",
        )

    # Telegram WebApp frontend
    # Keep URL stable (/webapp/*) independent from static/media settings.
    app.mount(
        "/webapp",
        StaticFiles(directory="backend/web/webapp", html=True),
        name="webapp",
    )
