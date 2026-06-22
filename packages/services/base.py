from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from redis.asyncio import Redis

from packages.db.database import Database
from packages.redis import ttl
from packages.redis.lock_repository import RedisLockRepository


class BaseService:
    def __init__(self, db: Database, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    @asynccontextmanager
    async def _lock(self, key: str) -> AsyncIterator[None]:
        lock = await RedisLockRepository.acquire(self.redis, key=key, ttl_sec=ttl.LOCK)
        try:
            yield
        finally:
            if lock:
                with suppress(Exception):
                    await RedisLockRepository.release(self.redis, lock)
