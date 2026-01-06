import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from redis.asyncio import Redis

from packages.db.database import Database
from packages.db.repository import RecipeRepository, UserRepository
from packages.db.schemas import UserCreate

if TYPE_CHECKING:
    from telegram import User as TelegramUser

from packages.redis import ttl
from packages.redis.keys import RedisKeys
from packages.redis.repository import (
    RecipeCacheRepository,
    UserCacheRepository,
)
from packages.redis.utils import acquire_lock, release_lock

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: Database, redis: Redis):
        self.db = db
        self.redis = redis

    async def ensure_user_exists_and_count(self, tg_user: "TelegramUser") -> int:
        """
        1) Пытаемся взять exists и count из Redis.
        2) Если чего-то нет — проверяем БД / создаём (под локом).
        3) Обновляем кэш и возвращаем recipe_count.
        """
        user_id = tg_user.id
        exists = await UserCacheRepository.get_exists(self.redis, user_id)
        recipe_count = await RecipeCacheRepository.get_recipe_count(self.redis, user_id)
        logger.debug(f"👉 User {user_id} exists={exists} count={recipe_count}")
        if exists is None:
            lock_key = RedisKeys.user_init_lock(user_id=user_id)
            token: str | None = await acquire_lock(self.redis, lock_key, ttl.LOCK)
            logger.debug(f"🔒 User {user_id} lock: {lock_key} token: {token}")
            try:
                async with self.db.session() as self.session:
                    user = await UserRepository.get_by_id(self.session, user_id)
                    logger.debug(f"👉 User {user_id} from DB: {user}")
                    if user is None:
                        payload = UserCreate(
                            id=tg_user.id,
                            username=tg_user.username,
                            first_name=tg_user.first_name,
                            last_name=tg_user.last_name,
                        )
                        user = await UserRepository.create(self.session, payload)
                    await UserCacheRepository.set_exists(self.redis, user.id)
            finally:
                if token:
                    with suppress(Exception):
                        await release_lock(self.redis, lock_key, token)

        if recipe_count is None:
            async with self.db.session() as self.session:
                recipe_count = await RecipeRepository.get_count_by_user(self.session, user_id)
                await RecipeCacheRepository.set_recipe_count(self.redis, user_id, recipe_count)
        return recipe_count
