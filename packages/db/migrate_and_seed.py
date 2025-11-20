from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.db.models import Admin
from packages.security.passwords import hash_password

ALEMBIC_INI_PATH = Path("/app/alembic.ini")


def _make_alembic_config(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _get_current_alembic_version(conn: Connection) -> Optional[str]:
    """Получаем текущую версию alembic из БД.
    Если таблица alembic_version есть.
    Если таблицы нет, возвращаем None.
    Если таблица есть, но в ней нет записей, возвращаем пустую строку.
    """
    exists = (
        conn.execute(
            text(
                """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'alembic_version'
        LIMIT 1
    """
            )
        ).scalar()
        is not None
    )

    if not exists:
        return None

    ver = conn.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).scalar()
    return str(ver) if ver else ""


def _has_user_tables(conn: Connection) -> bool:
    """Проверяем, есть ли в схеме public таблицы, кроме alembic_version
    (чтобы понять, инициализирована ли БД пользователем)
    """
    count = conn.execute(
        text(
            """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
          AND table_name NOT IN ('alembic_version')
    """
        )
    ).scalar()
    return (count or 0) > 0


def _probe_db_sync(db_url: str) -> tuple[str | None, bool]:
    """
    Синхронная проверка состояния БД.
    Возвращает (alembic_version | None, has_user_tables).
    Выполняется в отдельном треде.
    """
    # Таймауты для PostgreSQL: подключение и statement_timeout (5с)
    engine = create_engine(
        db_url,
        future=True,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            # Для psycopg/psycopg2 можно прокинуть statement_timeout так:
            "options": "-c statement_timeout=5000",
        },
    )
    try:
        with engine.connect() as conn:  # type: Connection
            current = _get_current_alembic_version(conn)
            has_tables = _has_user_tables(conn)
        return current, has_tables
    finally:
        engine.dispose()


async def ensure_db_up_to_date(db_url: str) -> None:
    """
    Идемпотентный апгрейд:
    - если нет alembic_version и нет пользовательских таблиц -> upgrade head
    - если нет alembic_version, но таблицы уже есть -> stamp head
    - если alembic_version есть -> upgrade head
    Вся синхронная работа уносится в отдельный поток, чтобы не блокировать loop.
    """
    # 1) Быстрая (но теперь неблокирующая для loop) проверка состояния БД
    current, has_tables = await asyncio.to_thread(_probe_db_sync, db_url)

    # 2) Решение + сами миграции (alembic command.* — синхронные; уносим в тред)
    cfg = _make_alembic_config(db_url)

    if current is None and has_tables:
        # Таблицы есть, но Alembic о них не знает — помечаем текущую схему как head
        await asyncio.to_thread(command.stamp, cfg, "head")
        return

    # Иначе применяем недостающие миграции
    await asyncio.to_thread(command.upgrade, cfg, "head")


async def ensure_admin(db: Database) -> None:
    """
    Создаёт администратора из settings, если его ещё нет.
    Не делает ничего, если логин/пароль не заданы или флаг отключён.
    """
    adm = settings.admin
    if not adm.create_on_startup or not adm.login or not adm.password:
        return

    async with db.session() as session:  # AsyncSession
        await _ensure_admin_in_session(
            session, adm.login, adm.password.get_secret_value()
        )


async def _ensure_admin_in_session(
    session: AsyncSession, login: str, raw_password: str
) -> None:
    # Ищем по логину
    res = await session.execute(select(Admin).where(Admin.login == login))
    existing: Optional[Admin] = res.scalar_one_or_none()
    if existing:
        return

    # Создаём
    admin = Admin(login=login, password_hash=hash_password(raw_password))
    session.add(admin)
    await session.commit()
