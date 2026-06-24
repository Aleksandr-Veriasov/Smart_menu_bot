from sqlalchemy.exc import IntegrityError

from packages.db.models import User
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
