import logging

from packages.db.repository import CategoryRepository
from packages.db.schemas import CategoryRead
from packages.redis.repository import CategoryCacheRepository
from packages.services.base import BaseService

logger = logging.getLogger(__name__)


class CategoryService(BaseService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_cache = CategoryCacheRepository(self.redis)
        self.category_repo = CategoryRepository

    async def get_user_categories_cached(self, user_id: int) -> list[CategoryRead]:
        """Категории пользователя с кешированием в Redis."""
        cached = await self.category_cache.get_user_categories(user_id)
        logger.debug(f"👉 Пользователь {user_id}: категории из кэша: {cached}")
        if cached:
            return [CategoryRead.model_validate(d) for d in cached]

        async with self._lock(self.keys.user_init_lock(user_id=user_id)):
            async with self.db.session() as session:
                categories = await self.category_repo(session).get_by_user_id(user_id)
                result = [CategoryRead.model_validate(c) for c in categories]
                await self.category_cache.set_user_categories(user_id, [r.model_dump() for r in result])
        return result

    async def get_id_and_name_by_slug_cached(self, slug: str) -> CategoryRead:
        """Категория по slug — ищет в общем кэше всех категорий."""
        all_categories = await self.get_all_category()
        for cat in all_categories:
            if cat.slug == slug:
                return cat
        raise ValueError(f'Категория со slug="{slug}" не найдена')

    async def get_all_category(self) -> list[CategoryRead]:
        """Все категории с кешированием в Redis."""
        cached = await self.category_cache.get_all_name_and_slug()
        logger.debug(f"👉 Все категории из кэша: {cached}")
        if cached:
            return [CategoryRead.model_validate(d) for d in cached]

        async with self._lock(self.keys.catergory_lock()):
            async with self.db.session() as session:
                categories = await self.category_repo(session).get_all()
                result = [CategoryRead.model_validate(c) for c in categories]
                await self.category_cache.set_all_name_and_slug([r.model_dump() for r in result])
                logger.debug(f"👉 Все категории из БД: {result}")
        return result
