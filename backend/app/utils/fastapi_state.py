from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis
from starlette.routing import Mount

from packages.app_state import AppState
from packages.db.database import Database


def get_app_state(request: Request) -> AppState:
    """Достаёт AppState из FastAPI app.state — единая точка доступа к ресурсам приложения."""
    app_state = getattr(request.app.state, "app_state", None)
    if app_state is None:
        raise HTTPException(status_code=500, detail="AppState не настроен (app.state.app_state отсутствует)")
    return app_state


def get_backend_db(request: Request) -> Database:
    """
    Достаёт Database из AppState.
    Нейминг специально с 'backend', чтобы не путать с bot/* хелперами.
    """
    return get_app_state(request).db


def get_backend_redis(request: Request) -> Redis:
    """
    Достаёт Redis из AppState.
    Если Redis не поднят/не подключён, бросает HTTP 503.
    """
    redis = get_app_state(request).redis
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis недоступен")
    return redis


def get_backend_redis_optional(request: Request) -> Redis | None:
    """
    Достаёт Redis из AppState, но не падает, если Redis недоступен.
    Используется для best-effort операций (инвалидация кешей, обновление сообщений и т.п.).
    """
    return get_app_state(request).redis


def propagate_state_to_mounted_apps(app: FastAPI, *, state: AppState) -> None:
    """
    SQLAdmin монтируется как sub-app. Для таких sub-app `request.app.state.*` не совпадает с корневым FastAPI app.state.
    Прописываем ссылку на AppState один раз — дальнейшие мутации state (redis, tasks) видны автоматически.
    """
    for route in getattr(app, "routes", []) or []:
        if not isinstance(route, Mount):
            continue
        try:
            sub_app = route.app
        except Exception:
            continue
        if sub_app is None or not hasattr(sub_app, "state"):
            continue
        sub_app.state.app_state = state
