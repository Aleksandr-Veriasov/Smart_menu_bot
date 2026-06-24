from typing import Any, Generic, TypeVar

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

M = TypeVar("M")


async def fetch_all(session: AsyncSession, stmt: Select[tuple[M]]) -> list[M]:
    """Выполнить SELECT и вернуть список объектов."""
    return list(await session.scalars(stmt))


class SessionMixin:
    """Базовый класс с сессией и методом save для репозиториев без привязки к модели."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, obj: Any) -> Any:
        """Сбросить изменения в БД и обновить объект из БД. При ошибке делает rollback."""
        try:
            await self.session.flush()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(obj)
        return obj


class BaseRepository(SessionMixin, Generic[M]):
    """Базовый репозиторий с типизированной моделью и CRUD-методами."""

    model: type[M]

    async def get_by_id(self, id: int) -> M | None:
        """Найти запись по первичному ключу."""
        return await self.session.get(self.model, id)

    async def delete(self, id: int) -> None:
        """Удалить запись по id. Raises ValueError если не найдена."""
        obj = await self.get_by_id(id)
        if obj is None:
            raise ValueError(f"{self.model.__name__} not found")
        await self.session.delete(obj)

    async def update_fields(self, id: int, changes: dict[str, Any]) -> M:
        """Обновить указанные поля записи. Raises ValueError если не найдена."""
        obj = await self.get_by_id(id)
        if obj is None:
            raise ValueError(f"{self.model.__name__} not found")
        for key, value in changes.items():
            setattr(obj, key, value)
        return await self.save(obj)
