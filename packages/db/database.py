import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from packages.common_settings.settings import settings

logger = logging.getLogger(__name__)


class Database:
    """
    Асинхронный менеджер БД на SQLAlchemy 2.0.

    - Управляет AsyncEngine и AsyncSession.
    - Можно передать готовый AsyncEngine (для тестов) или URL (str/URL).
    - URL должен быть АСИНХРОННЫМ (postgresql+asyncpg).
    """

    def __init__(
        self,
        db_url: str | URL | None = None,
        engine: AsyncEngine | None = None,
        *,
        echo: bool = False,
        pool_pre_ping: bool = settings.db.pool_pre_ping,
        pool_recycle: int = settings.db.pool_recycle,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        pool_timeout: int | None = None,
        null_pool: bool = False,
    ) -> None:
        if engine is not None:
            self.engine: AsyncEngine = engine
            safe = getattr(
                engine.sync_engine.url,
                "render_as_string",
                lambda **_: "<engine>",
            )(hide_password=True)
            logger.info("🚀 Async DB engine подключён извне: %s", safe)
        else:
            url = db_url or settings.db.sqlalchemy_url(use_async=True)
            # защита от sync-драйвера в асинхронном классе
            is_async = (isinstance(url, URL) and url.drivername.endswith("+asyncpg")) or (
                isinstance(url, str) and "asyncpg" in url
            )

            if not is_async:
                raise ValueError(
                    "Получен sync-драйвер для асинхронного Database. " "Соберите async URL (postgresql+asyncpg)."
                )

            if echo is None:
                echo = settings.debug
            if pool_pre_ping is None:
                pool_pre_ping = settings.db.pool_pre_ping
            if pool_recycle is None:
                pool_recycle = settings.db.pool_recycle

            engine_kwargs: dict[str, Any] = {"echo": echo}
            if null_pool:
                # без пула: соединение создаётся на каждый запрос и сразу закрывается
                engine_kwargs["poolclass"] = NullPool
            else:
                engine_kwargs["pool_pre_ping"] = pool_pre_ping
                engine_kwargs["pool_recycle"] = pool_recycle
                if pool_size is not None:
                    engine_kwargs["pool_size"] = pool_size
                if max_overflow is not None:
                    engine_kwargs["max_overflow"] = max_overflow
                if pool_timeout is not None:
                    engine_kwargs["pool_timeout"] = pool_timeout

            self.engine = create_async_engine(url, **engine_kwargs)

            safe = url.render_as_string(hide_password=True) if isinstance(url, URL) else "<masked url>"
            logger.info("🚀 Async DB engine создан для %s", safe)

        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    async def dispose(self) -> None:
        """Закрыть все соединения пула (использовать при shutdown)."""
        await self.engine.dispose()
        logger.info("🧹 Async DB engine освобождён")

    def get_session(self) -> AsyncSession:
        """Создать новую асинхронную сессию (не забывай закрыть!)."""
        logger.debug("💾 Создаём Async DB сессию")
        return self._sessionmaker()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Контекстный менеджер с авто-commit/rollback.

        Пример:
            async with db.session() as session:
                session.add(obj)
        """
        session: AsyncSession = self.get_session()
        try:
            yield session
            await session.commit()
        except Exception:
            logger.exception("❌ Ошибка в Async DB сессии")
            await session.rollback()
            raise
        finally:
            await session.close()
            logger.debug("🔒 Async DB сессия закрыта")

    async def healthcheck(self) -> bool:
        """Лёгкая проверка доступности БД (async)."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("❌ Проверка доступности БД завершилась ошибкой")
            return False
