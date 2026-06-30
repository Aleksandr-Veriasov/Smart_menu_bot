from sqlalchemy import select

from packages.db.models import Admin

from .base import SessionMixin


class AdminRepository(SessionMixin):
    async def get_by_login(self, login: str) -> Admin | None:
        result = await self.session.execute(select(Admin).where(Admin.login == login))
        return result.scalar_one_or_none()
