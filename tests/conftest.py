"""Pytest configuration and fixtures for all tests."""

import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Configure pytest-asyncio to use auto mode (creates event loop for each test)
pytest_plugins = ("pytest_asyncio",)

logger = logging.getLogger(__name__)


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from a local env file if present."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(Path(__file__).resolve().parents[1] / ".env.test")


# Configure asyncio mode
def pytest_configure(config):
    """Configure pytest-asyncio mode."""
    config.option.asyncio_mode = "auto"


def get_test_database_url() -> str:
    """Получить URL тестовой БД из окружения или использовать дефолт.

    Приоритет:
    1. TEST_DATABASE_URL env переменная (GitHub Actions)
    2. DATABASE_TEST_URL env переменная
    3. Локальный PostgreSQL дефолт (создан setup-test-db.sh)
    """
    test_url = os.getenv("TEST_DATABASE_URL")
    if test_url:
        return test_url

    test_url = os.getenv("DATABASE_TEST_URL")
    if test_url:
        return test_url

    # Local default (matches setup-test-db.sh credentials)
    return "postgresql://test_user:test_password@localhost:5432/test_smartmenubot"


def get_sync_database_url() -> str:
    """Получить синхронный URL БД для миграций."""
    url = get_test_database_url()
    # Convert asyncpg to psycopg3 for sync operations
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _reset_public_schema(engine) -> None:
    """Удалить все таблицы в public schema перед прогоном миграций.

    Тестовая база должна быть disposable. Если в ней уже есть таблицы
    от предыдущих запусков, Alembic будет падать на create_table().
    """
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))


@pytest.fixture(scope="session")
def test_db_engine():
    """Создать синхронный engine для миграций.

    Fixture:
    - Создает engine для тестовой БД
    - Запускает все миграции
    - Возвращает engine
    - Очищает после тестов
    """
    sync_url = get_sync_database_url()
    logger.info(f"Connecting to test database: {sync_url}")

    engine = create_engine(sync_url, echo=False)

    # Проверка подключения
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            logger.info("✅ Database connection successful")
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        raise

    # Запуск миграций
    try:
        _reset_public_schema(engine)
        from alembic.command import upgrade
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
        upgrade(alembic_cfg, "head")
        logger.info("✅ Migrations applied successfully")
    except Exception as e:
        logger.error(f"❌ Failed to run migrations: {e}")
        raise

    yield engine

    # Cleanup
    engine.dispose()
    logger.info("✅ Test database engine closed")


@pytest.fixture(scope="function")
def test_async_engine():
    """Создать асинхронный engine для асинхронных тестов.

    Function scope чтобы избежать конфликтов event loop между тестами.
    """
    async_url = get_test_database_url()
    # Ensure we have asyncpg dialect
    if "asyncpg" not in async_url:
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")

    logger.info("Creating async engine for tests")
    return create_async_engine(async_url, echo=False)


@pytest.fixture(scope="function")
def test_session_factory(test_async_engine):
    """Создать фабрику асинхронных сессий для тестовой БД.

    Function scope чтобы соответствовать test_async_engine scope.
    """
    return async_sessionmaker(bind=test_async_engine, class_=AsyncSession, expire_on_commit=False)


async def _truncate_tables(engine) -> None:
    """Очистить тестовые таблицы используя отдельное соединение."""
    async with engine.connect() as conn:
        # Get all tables and truncate them in reverse order to respect FK constraints
        tables_query = text(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename DESC
        """
        )
        result = await conn.execute(tables_query)
        tables = [row[0] for row in result.fetchall()]

        if tables:
            # Truncate all tables with CASCADE
            await conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
        await conn.commit()


@pytest_asyncio.fixture
async def db_session(test_db_engine, test_session_factory, test_async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Предоставить чистую тестовую сессию.

    Рабочий процесс:
    1. Очистить перед тестом (чистый лист)
    2. Создать сессию, запустить тест
    3. Коммитить изменения теста в БД
    4. Явно закрыть сессию (освободить asyncpg соединение)
    5. Очистить после теста (уборка)
    """
    # test_db_engine ensures migrations are applied before we touch the DB.
    # Clean before test using separate connection
    await _truncate_tables(test_async_engine)

    async with test_session_factory() as session:
        yield session
        # Commit changes from test to DB
        # (this allows refresh() to work properly without begin() nesting conflicts)
        await session.commit()
        # CRITICAL: Explicitly close the session to release the asyncpg connection
        # before we try to run truncate in a new connection
        await session.close()

    # Clean after test using fresh connection
    await _truncate_tables(test_async_engine)
