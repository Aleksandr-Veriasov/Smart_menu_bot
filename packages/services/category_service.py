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

    async def get_user_categories_cached(self, user_id: int) -> list[dict[str, str]]:
        """Категории пользователя с кешированием в Redis."""
        cached = await self.category_cache.get_user_categories(user_id)
        logger.debug(f"👉 Пользователь {user_id}: категории из кэша: {cached}")
        if cached:
            return cached

        async with self._lock(RedisKeys.user_init_lock(user_id=user_id)):
            async with self.db.session() as session:
                categories = await CategoryRepository(session).get_by_user_id(user_id)
                rows = [{"name": c.name, "slug": c.slug} for c in categories]
                await self.category_cache.set_user_categories(user_id, rows)
        return rows

    async def get_id_and_name_by_slug_cached(self, slug: str) -> tuple[int, str]:
        """Id и name категории по slug с кешированием в Redis."""
        cached = await self.category_cache.get_id_name_by_slug(slug)
        logger.debug(f"👉 Категория {slug}: id,name из кэша: {cached}")
        if cached:
            return cached

        async with self._lock(RedisKeys.slug_init_lock(slug)):
            async with self.db.session() as session:
                category = await CategoryRepository(session).get_by_slug(slug)
                logger.debug(f"👉 Категория {slug}: из БД: {category}")
                if category is None:
                    raise ValueError(f'Категория со slug="{slug}" не найдена')

                await self.category_cache.set_id_name_by_slug(slug, category.id, category.name)
        return category.id, category.name

    async def get_all_category(self) -> list[dict[str, int | str]]:
        """Все категории с кешированием в Redis."""
        cached = await self.category_cache.get_all_name_and_slug()
        logger.debug(f"👉 Все категории из кэша: {cached}")
        if cached:
            return cached

        async with self._lock(RedisKeys.catergory_lock()):
            async with self.db.session() as session:
                categories = await CategoryRepository(session).get_all()
                rows = [{"id": c.id, "name": c.name, "slug": c.slug} for c in categories]
                await self.category_cache.set_all_name_and_slug(rows)
                logger.debug(f"👉 Все категории из БД: {rows}")
        return rows
