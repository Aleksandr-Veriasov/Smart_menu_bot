"""Аутентификация для admin_v2: login/logout и FastAPI-зависимость."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.database import Database
from packages.db.models import Admin as AdminModel
from packages.security.passwords import verify_password


async def _get_admin_by_login(session: AsyncSession, login: str) -> AdminModel | None:
    result = await session.execute(select(AdminModel).where(AdminModel.login == login))
    return result.scalar_one_or_none()


async def authenticate(login: str, password: str, db: Database) -> bool:
    async with db.session() as session:
        admin = await _get_admin_by_login(session, login)
    if not admin:
        return False
    return verify_password(password, str(admin.password_hash))


def require_admin_v2(request: Request) -> None:
    if "admin_login" not in request.session:
        raise _LoginRedirect()


class _LoginRedirect(Exception):
    pass


def get_current_admin_login(request: Request) -> str:
    return request.session.get("admin_login", "")
