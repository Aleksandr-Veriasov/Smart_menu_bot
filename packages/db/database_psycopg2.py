import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from packages.common_settings.settings import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Точка сборки ORM-моделей. Импортируй её в models.py и наследуйся."""

    pass


class Database:
    """
    Синхронный менеджер БД на SQLAlchemy 2.0.

    - Управляет sync Engine и Session.
    - Можно передать готовый Engine (для тестов) или URL (str/URL).
    - URL должен быть СИНХРОННЫМ (postgresql+psycopg2 / postgresql+psycopg).
    """

    def __init__(
        self,
        db_url: str | URL | None = None,
        engine: Engine | None = None,
        *,
        echo: bool = False,
        pool_pre_ping: bool = settings.db.pool_pre_ping,
        pool_recycle: int = settings.db.pool_recycle,
        pool_size: int | None = None,
        max_overflow: int | None = None,
        pool_timeout: int | None = None,
    ) -> None:
        if engine is not None:
            self.engine = engine
            safe = getattr(engine.url, "render_as_string", lambda **_: "<engine>")(hide_password=True)
            logger.info("🚀 DB engine injected: %s", safe)
        else:
            url = db_url or settings.db.sqlalchemy_url(use_async=True)
            # защита от async-драйвера в синхронном классе
            if (isinstance(url, URL) and url.drivername.endswith("+asyncpg")) or (
                isinstance(url, str) and "asyncpg" in url
            ):
                raise ValueError(
                    "Получен async-драйвер (asyncpg) для синхронного Database."
                    "Соберите sync URL (postgresql+psycopg2 / "
                    "postgresql+psycopg)."
                )

            # разумные дефолты, если не заданы аргументами
            if echo is None:
                echo = settings.debug
            if pool_pre_ping is None:
                pool_pre_ping = settings.db.pool_pre_ping
            if pool_recycle is None:
                pool_recycle = settings.db.pool_recycle

            engine_kwargs: dict[str, object] = {
                "echo": echo,
                "pool_pre_ping": pool_pre_ping,
                "pool_recycle": pool_recycle,
            }
            if pool_size is not None:
                engine_kwargs["pool_size"] = pool_size
            if max_overflow is not None:
                engine_kwargs["max_overflow"] = max_overflow
            if pool_timeout is not None:
                engine_kwargs["pool_timeout"] = pool_timeout

            self.engine = create_engine(url, **engine_kwargs)

            safe = url.render_as_string(hide_password=True) if isinstance(url, URL) else "<masked url>"
            logger.info("🚀 DB engine created for %s", safe)

        self._sessionmaker: sessionmaker[Session] = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session,
        )

    def dispose(self) -> None:
        """Закрыть все соединения пула (использовать при shutdown)."""
        self.engine.dispose()
        logger.info("🧹 DB engine disposed")

    def get_session(self) -> Session:
        """Создать новую сессию (не забывай закрыть!)."""
        logger.debug("💾 Creating DB session")
        return self._sessionmaker()

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Контекстный менеджер с авто-commit/rollback.

        Пример:
            async with db.session() as session:
                session.add(obj)
        """
        session: Session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            logger.exception("❌ Error in async DB session")
            session.rollback()
            raise
        finally:
            session.close()
            logger.debug("🔒 Async DB session closed")

    def healthcheck(self) -> bool:
        """Лёгкая проверка доступности БД."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.exception("❌ DB healthcheck failed")
            return False

    def create_all(self, base_metadata: MetaData) -> None:
        """
        Bootstrap схемы (dev-only).
        Пример: db.create_all(Base.metadata)
        """
        with self.engine.begin() as conn:
            base_metadata.create_all(bind=conn)
        logger.info("📦 Metadata.create_all() done")
