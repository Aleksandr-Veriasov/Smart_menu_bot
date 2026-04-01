import logging
from contextlib import suppress

from redis.asyncio import Redis

from packages.db.database import Database
from packages.db.repository import CategoryRepository
from packages.redis import ttl
from packages.redis.keys import RedisKeys
from packages.redis.lock_repository import RedisLockRepository
from packages.redis.repository import CategoryCacheRepository

logger = logging.getLogger(__name__)


class CategoryService:
    def __init__(self, db: Database, redis: Redis):
        self.db = db
        self.redis = redis

    async def get_user_categories_cached(self, user_id: int) -> list[dict[str, str]]:
        """
        Получить категории пользователя с кешированием в Redis.
        Возвращает список словарей с ключами 'name' и 'slug'.
        """
        # 1) пробуем Redis
        cached = await CategoryCacheRepository.get_user_categories(self.redis, user_id)
        logger.debug(f"👉 Пользователь {user_id}: категории из кэша: {cached}")
        if cached:
            return cached

        # 2) БД
        lock_key = RedisKeys.user_init_lock(user_id=user_id)
        lock = await RedisLockRepository.acquire(self.redis, key=lock_key, ttl_sec=ttl.LOCK)
        try:
            async with self.db.session() as self.session:
                rows = await CategoryRepository.get_name_and_slug_by_user_id(self.session, user_id)
                await CategoryCacheRepository.set_user_categories(self.redis, user_id, rows)
        finally:
            if lock:
                with suppress(Exception):
                    await RedisLockRepository.release(self.redis, lock)
        return rows

    async def get_id_and_name_by_slug_cached(self, slug: str) -> tuple[int, str]:
        """
        Получить id и name категории по slug с кешированием в Redis.
        Возвращает кортеж (id, name).
        """
        # 1) Redis
        cached = await CategoryCacheRepository.get_id_name_by_slug(self.redis, slug)
        logger.debug(f"👉 Категория {slug}: id,name из кэша: {cached}")
        if cached:
            return cached  # (id, name)

        # 2) DB
        lock_key = RedisKeys.slug_init_lock(slug)
        lock = await RedisLockRepository.acquire(self.redis, key=lock_key, ttl_sec=ttl.LOCK)
        try:
            async with self.db.session() as self.session:
                result = await CategoryRepository.get_id_and_name_by_slug(self.session, slug)
                logger.debug(f"👉 Категория {slug}: id,name из БД: {result}")
                if result is None or (isinstance(result, tuple) and any(v is None for v in result)):
                    raise ValueError(f'Категория со slug="{slug}" не найдена')

                category_id, category_name = result
                # 3) Persist в Redis (без TTL)
                await CategoryCacheRepository.set_id_name_by_slug(self.redis, slug, category_id, category_name)
        finally:
            if lock:
                with suppress(Exception):
                    await RedisLockRepository.release(self.redis, lock)
        return category_id, category_name

    async def get_all_category(self) -> list[dict[str, int | str]]:
        """
        Получить все категории с кешированием в Redis.
        Возвращает список словарей категорий.

        Минимальные ключи:
        - name: str
        - slug: str

        Также в кеше/ответе может присутствовать:
        - id: int
        """
        # 1) Redis
        cached = await CategoryCacheRepository.get_all_name_and_slug(self.redis)
        logger.debug(f"👉 Все категории из кэша: {cached}")
        if cached:
            return cached

        # 2) DB
        lock_key = RedisKeys.catergory_lock()
        lock = await RedisLockRepository.acquire(self.redis, key=lock_key, ttl_sec=ttl.LOCK)
        try:
            async with self.db.session() as self.session:
                # Храним в кеше также id, чтобы его могли использовать другие компоненты (например WebApp).
                rows = await CategoryRepository.get_all(self.session)
                await CategoryCacheRepository.set_all_name_and_slug(self.redis, rows)
                logger.debug(f"👉 Все категории из БД: {rows}")
        finally:
            if lock:
                with suppress(Exception):
                    await RedisLockRepository.release(self.redis, lock)
        return rows
