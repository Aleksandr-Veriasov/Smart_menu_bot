import logging

from packages.db.repository import CategoryRepository
from packages.redis.keys import RedisKeys
from packages.redis.repository import CategoryCacheRepository
from packages.services.base import BaseService

logger = logging.getLogger(__name__)


class CategoryService(BaseService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_cache = CategoryCacheRepository(self.redis)
        self.category_repo = CategoryRepository

    async def get_user_categories_cached(self, user_id: int) -> list[dict[str, str]]:
        """Категории пользователя с кешированием в Redis."""
        cached = await self.category_cache.get_user_categories(user_id)
        logger.debug(f"👉 Пользователь {user_id}: категории из кэша: {cached}")
        if cached:
            return cached

        async with self._lock(RedisKeys.user_init_lock(user_id=user_id)):
            async with self.db.session() as self.session:
                rows = await self.category_repo.get_name_and_slug_by_user_id(self.session, user_id)
                await self.category_cache.set_user_categories(user_id, rows)
        return rows

    async def get_id_and_name_by_slug_cached(self, slug: str) -> tuple[int, str]:
        """Id и name категории по slug с кешированием в Redis."""
        cached = await self.category_cache.get_id_name_by_slug(slug)
        logger.debug(f"👉 Категория {slug}: id,name из кэша: {cached}")
        if cached:
            return cached

        async with self._lock(RedisKeys.slug_init_lock(slug)):
            async with self.db.session() as self.session:
                result = await self.category_repo.get_id_and_name_by_slug(self.session, slug)
                logger.debug(f"👉 Категория {slug}: id,name из БД: {result}")
                if result is None or (isinstance(result, tuple) and any(v is None for v in result)):
                    raise ValueError(f'Категория со slug="{slug}" не найдена')

                category_id, category_name = result
                await self.category_cache.set_id_name_by_slug(slug, category_id, category_name)
        return category_id, category_name

    async def get_all_category(self) -> list[dict[str, int | str]]:
        """Все категории с кешированием в Redis."""
        cached = await self.category_cache.get_all_name_and_slug()
        logger.debug(f"👉 Все категории из кэша: {cached}")
        if cached:
            return cached

        async with self._lock(RedisKeys.catergory_lock()):
            async with self.db.session() as self.session:
                rows = await self.category_repo.get_all(self.session)
                await self.category_cache.set_all_name_and_slug(rows)
                logger.debug(f"👉 Все категории из БД: {rows}")
        return rows
