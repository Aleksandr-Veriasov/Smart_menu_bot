import logging
from contextlib import suppress

from redis.asyncio import Redis

from packages.db.database import Database
from packages.db.repository import RecipeRepository, RecipeUserRepository
from packages.redis import ttl
from packages.redis.keys import RedisKeys
from packages.redis.repository import RecipeCacheRepository
from packages.redis.utils import acquire_lock, release_lock

logger = logging.getLogger(__name__)


class RecipeService:
    def __init__(self, db: Database, redis: Redis):
        self.db = db
        self.redis = redis

    async def get_all_recipes_ids_and_titles(self, user_id: int, category_id: int) -> list[dict[str, int | str]]:
        """
        Получить все id и названия рецептов пользователя.
        """
        # 1) пробуем Redis
        cached = await RecipeCacheRepository.get_all_recipes_ids_and_titles(self.redis, user_id, category_id)
        logger.debug(f"👉 Пользователь: {user_id} категория: {category_id} " f"название рецептов и id: {cached}")
        if cached:
            return cached

        # 2) БД
        lock_key = RedisKeys.user_init_lock(user_id=user_id)
        token: str | None = await acquire_lock(self.redis, lock_key, ttl.LOCK)
        try:
            async with self.db.session() as self.session:
                rows = await RecipeRepository.get_all_recipes_ids_and_titles(self.session, user_id, category_id)
                await RecipeCacheRepository.set_all_recipes_ids_and_titles(self.redis, user_id, category_id, rows)
        finally:
            if token:
                with suppress(Exception):
                    await release_lock(self.redis, lock_key, token)
        logger.debug(f"👉 Пользователь: {user_id} категория: {category_id} " f"название рецептов и id из БД: {rows}")
        return rows

    async def delete_recipe(self, user_id: int, recipe_id: int) -> None:
        """Удаляет связь рецепт-пользователь и инвалидирует кэш."""
        async with self.db.session() as session:
            category_id = await RecipeRepository.get_category_id_by_recipe_id(session, recipe_id, user_id)
            logger.debug(f"👉 Рецепт {recipe_id} category_id: {category_id}")
            await RecipeUserRepository.unlink_user(session, recipe_id, user_id)
            await session.commit()
        if category_id is not None:
            await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(self.redis, user_id, category_id)
            # Обновляем кэш рецептов
            await self.get_all_recipes_ids_and_titles(user_id=user_id, category_id=category_id)

    async def update_recipe_title(self, user_id: int, recipe_id: int, new_title: str) -> None:
        """Обновляет название рецепта и инвалидирует кэш."""
        async with self.db.session() as session:
            category_id = await RecipeRepository.get_category_id_by_recipe_id(session, recipe_id, user_id)
            logger.debug(f"👉 Рецепт {recipe_id} category_id: {category_id}")
            await RecipeRepository.update_title(session, recipe_id, new_title)
        if category_id is not None:
            await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(self.redis, user_id, category_id)
            # Обновляем кэш рецептов
            await self.get_all_recipes_ids_and_titles(user_id=user_id, category_id=category_id)
