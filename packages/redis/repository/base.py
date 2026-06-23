from redis.asyncio import Redis


class BaseRedisRepository:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
