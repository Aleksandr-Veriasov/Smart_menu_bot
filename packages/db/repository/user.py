from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from packages.db.models import Recipe, User
from packages.db.schemas import UserCreate, UserUpdate

from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Репозиторий для работы с пользователями."""

    model = User

    async def create(self, payload: UserCreate) -> User:
        """Создать пользователя. Raises ValueError при дублировании id."""
        data = payload.model_dump(exclude_unset=True, exclude_none=True)
        user = self.model(**data)
        self.session.add(user)
        try:
            return await self.save(user)
        except IntegrityError as exc:
            raise ValueError("User already exists") from exc

    async def update(self, user_id: int, payload: UserUpdate) -> User:
        """Обновить поля пользователя из payload."""
        return await self.update_fields(user_id, payload.model_dump(exclude_unset=True, exclude_none=True))

    async def search_by_username(self, q: str, limit: int = 10) -> list[User]:
        """Найти пользователей по подстроке в username (ilike)."""
        stmt = select(self.model).where(self.model.username.ilike(f"%{q}%")).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_page(self, *, offset: int, limit: int, q: str) -> tuple[list[User], int]:
        """Страница пользователей с опциональным поиском по username/first_name."""
        base = select(self.model)
        if q:
            base = base.where(self.model.username.ilike(f"%{q}%") | self.model.first_name.ilike(f"%{q}%"))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = (
            base.options(joinedload(self.model.linked_recipes))
            .order_by(self.model.id.desc())
            .offset(offset)
            .limit(limit)
        )
        users = list((await self.session.execute(stmt)).unique().scalars().all())
        return users, int(total)

    async def get_with_recipes(self, user_id: int) -> User | None:
        """Пользователь с загруженными рецептами и видео."""
        stmt = (
            select(self.model)
            .where(self.model.id == user_id)
            .options(joinedload(self.model.linked_recipes).joinedload(Recipe.video))
        )
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()
