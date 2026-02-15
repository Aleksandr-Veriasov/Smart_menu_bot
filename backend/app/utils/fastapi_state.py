from __future__ import annotations

from fastapi import HTTPException, Request
from redis.asyncio import Redis

from packages.db.database import Database


def get_backend_db(request: Request) -> Database:
    """
    Достаёт Database из FastAPI app.state.
    Нейминг специально с 'backend', чтобы не путать с bot/* хелперами.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=500, detail="База данных не настроена (app.state.db отсутствует)")
    return db


def get_backend_redis(request: Request) -> Redis:
    """
    Достаёт Redis из FastAPI app.state.

    Если Redis не поднят/не подключён, бросает HTTP 503.
    """
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis недоступен")
    return redis


def get_backend_redis_optional(request: Request) -> Redis | None:
    """
    Достаёт Redis из FastAPI app.state, но не падает, если Redis недоступен.

    Используется для best-effort операций (инвалидация кешей, обновление сообщений и т.п.).
    """

    return getattr(request.app.state, "redis", None)
