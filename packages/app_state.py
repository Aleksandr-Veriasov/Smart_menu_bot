from dataclasses import dataclass
from typing import Any

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
    cleanup_task: Any | None = None  # сюда можно класть фоновые таски/хэндлы
    backup_task: Any | None = None
    redis: Redis | None = None


__all__ = ["AppState"]
