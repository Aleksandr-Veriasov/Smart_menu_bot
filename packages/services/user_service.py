import logging

from packages.db.models import User
from packages.db.repository import RecipeRepository
from packages.db.repository.user import UserRepository
from packages.db.schemas import UserCreate
from packages.redis.repository import RecipeCacheRepository, UserCacheRepository
from packages.services.base import BaseService

logger = logging.getLogger(__name__)


class UserService(BaseService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_repo = UserRepository
        self.user_cache = UserCacheRepository(self.redis)
        self.recipe_cache = RecipeCacheRepository(self.redis)

    async def ensure_user_exists(self, user_data: UserCreate) -> None:
        """Гарантирует, что пользователь существует в БД, и кэширует факт существования."""
        user_id = user_data.id
        exists = await self.user_cache.get_exists(user_id)
        logger.debug("👉 Пользователь %s: существует=%s", user_id, exists)
        if exists is not None:
            return

        async with self._lock(self.keys.user_init_lock(user_id=user_id)):
            async with self.db.session() as session:
                repo = self.user_repo(session)
                user = await repo.get_by_id(user_id)
                logger.debug("👉 Пользователь %s из БД: %s", user_id, user)
                if user is None:
                    user = await repo.create(user_data)
                await self.user_cache.set_exists(user.id)

    async def get_recipe_count(self, user_id: int) -> int:
        """Возвращает количество рецептов пользователя с кэшированием в Redis."""
        recipe_count = await self.recipe_cache.get_recipe_count(user_id)
        logger.debug("👉 Пользователь %s: count=%s", user_id, recipe_count)
        if recipe_count is None:
            async with self.db.session() as session:
                recipe_count = await RecipeRepository(session).get_count_by_user(user_id)
                await self.recipe_cache.set_recipe_count(user_id, recipe_count)
        return recipe_count

    async def list_page(self, page: int, page_size: int, q: str = "") -> tuple[list[User], int]:
        """Страница пользователей для admin-панели."""
        async with self.db.session() as session:
            return await self.user_repo(session).list_page(offset=(page - 1) * page_size, limit=page_size, q=q)

    async def get_or_raise(self, user_id: int) -> User:
        """Пользователь с рецептами или LookupError."""
        async with self.db.session() as session:
            user = await self.user_repo(session).get_with_recipes(user_id)
        if user is None:
            raise LookupError(f"Пользователь #{user_id} не найден")
        return user
