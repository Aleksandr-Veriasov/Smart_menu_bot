from redis.asyncio import Redis

from packages.redis import ttl
from packages.redis.keys import RedisKeys


class BaseRedisRepository:
    keys = RedisKeys
    ttl = ttl

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
