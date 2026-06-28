import asyncio
from dataclasses import dataclass

from redis.asyncio import Redis

# Импорт только для подсказок типов (не вызывает циклических импортов
# в рантайме)
from packages.db.database import Database


@dataclass(slots=True)
class AppState:
    """
    Единый контейнер состояния приложения.
    Хранит долгоживущие ресурсы (БД и т.п.).
    """

    db: Database
    cleanup_task: asyncio.Task[None] | None = None  # хэндлы фоновых задач
    backup_task: asyncio.Task[None] | None = None
    broadcast_task: asyncio.Task[None] | None = None
    redis: Redis | None = None


__all__ = ["AppState"]
