import logging
from contextlib import suppress
from typing import Dict, List, Optional, Tuple

from redis.asyncio import Redis

from packages.db.database import Database
from packages.db.repository import CategoryRepository
from packages.redis import ttl
from packages.redis.keys import RedisKeys
from packages.redis.repository import CategoryCacheRepository
from packages.redis.utils import acquire_lock, release_lock

logger = logging.getLogger(__name__)


class CategoryService:
    def __init__(self, db: Database, redis: Redis):
        self.db = db
        self.redis = redis

    async def get_user_categories_cached(
        self, user_id: int
    ) -> List[Dict[str, str]]:
        """
        Получить категории пользователя с кешированием в Redis.
        Возвращает список словарей с ключами 'name' и 'slug'.
        """
        # 1) пробуем Redis
        cached = await CategoryCacheRepository.get_user_categories(
            self.redis, user_id
        )
        logger.debug(f"👉 User {user_id} categories from cache: {cached}")
        if cached:
            return cached

        # 2) БД
        lock_key = RedisKeys.user_init_lock(user_id=user_id)
        token: Optional[str] = await acquire_lock(
            self.redis, lock_key, ttl.LOCK
        )
        try:
            async with self.db.session() as self.session:
                rows = await CategoryRepository.get_name_and_slug_by_user_id(
                    self.session, user_id
                )
                await CategoryCacheRepository.set_user_categories(
                    self.redis, user_id, rows
                )
        finally:
            if token:
                with suppress(Exception):
                    await release_lock(self.redis, lock_key, token)
        return rows

    async def get_id_and_name_by_slug_cached(
        self, slug: str
    ) -> Tuple[int, str]:
        """
        Получить id и name категории по slug с кешированием в Redis.
        Возвращает кортеж (id, name).
        """
        # 1) Redis
        cached = await CategoryCacheRepository.get_id_name_by_slug(
            self.redis, slug
        )
        logger.debug(f"👉 Category {slug} id,name from cache: {cached}")
        if cached:
            return cached  # (id, name)

        # 2) DB
        lock_key = RedisKeys.slug_init_lock(slug)
        token: Optional[str] = await acquire_lock(
            self.redis, lock_key, ttl.LOCK
        )
        try:
            async with self.db.session() as self.session:
                result = await CategoryRepository.get_id_and_name_by_slug(
                    self.session, slug
                )
                logger.debug(f"👉 Category {slug} id,name from DB: {result}")
                if result is None or (
                    isinstance(result, tuple) and any(v is None for v in result)
                ):
                    raise ValueError(f'Category with slug="{slug}" not found')

                category_id, category_name = result
                # 3) Persist в Redis (без TTL)
                await CategoryCacheRepository.set_id_name_by_slug(
                    self.redis, slug, category_id, category_name
                )
        finally:
            if token:
                with suppress(Exception):
                    await release_lock(self.redis, lock_key, token)
        return category_id, category_name

    async def get_all_category(self) -> List[Dict[str, str]]:
        """
        Получить все категории с кешированием в Redis.
        Возвращает список словарей с ключами 'name' и 'slug'.
        """
        # 1) Redis
        cached = await CategoryCacheRepository.get_all_name_and_slug(self.redis)
        logger.debug(f"👉 All categories from cache: {cached}")
        if cached:
            return cached

        # 2) DB
        lock_key = RedisKeys.catergory_lock()
        token: Optional[str] = await acquire_lock(
            self.redis, lock_key, ttl.LOCK
        )
        try:
            async with self.db.session() as self.session:
                rows = await CategoryRepository.get_all_name_and_slug(
                    self.session
                )
                await CategoryCacheRepository.set_all_name_and_slug(
                    self.redis, rows
                )
                logger.debug(f"👉 All categories from DB: {rows}")
        finally:
            if token:
                with suppress(Exception):
                    await release_lock(self.redis, lock_key, token)
        return rows
