import logging

from packages.db.repository import RecipeRepository, UserRepository
from packages.db.schemas import UserCreate
from packages.redis.keys import RedisKeys
from packages.redis.repository import RecipeCacheRepository, UserCacheRepository
from packages.services.base import BaseService

logger = logging.getLogger(__name__)


class UserService(BaseService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_repo = UserRepository
        self.recipe_repo = RecipeRepository
        self.user_cache = UserCacheRepository
        self.recipe_cache = RecipeCacheRepository

    async def ensure_user_exists_and_count(self, user_data: UserCreate) -> int:
        """
        1) Пытаемся взять exists и count из Redis.
        2) Если чего-то нет — проверяем БД / создаём (под локом).
        3) Обновляем кэш и возвращаем recipe_count.
        """
        user_id = user_data.id
        exists = await self.user_cache.get_exists(self.redis, user_id)
        recipe_count = await self.recipe_cache.get_recipe_count(self.redis, user_id)
        logger.debug(f"👉 Пользователь {user_id}: существует={exists} count={recipe_count}")
        if exists is None:
            async with self._lock(RedisKeys.user_init_lock(user_id=user_id)):
                async with self.db.session() as self.session:
                    user = await self.user_repo.get_by_id(self.session, user_id)
                    logger.debug(f"👉 Пользователь {user_id} из БД: {user}")
                    if user is None:
                        user = await self.user_repo.create(self.session, user_data)
                    await self.user_cache.set_exists(self.redis, user.id)

        if recipe_count is None:
            async with self.db.session() as self.session:
                recipe_count = await self.recipe_repo.get_count_by_user(self.session, user_id)
                await self.recipe_cache.set_recipe_count(self.redis, user_id, recipe_count)
        return recipe_count
