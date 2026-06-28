import os

from redis.asyncio import Redis

from packages.common_settings.settings import settings

_redis: Redis | None = None

_SINGLE_CONN = os.getenv("REDIS_SINGLE_CONN", "0") == "1"
_MAX_CONNECTIONS = int(os.getenv("REDIS_POOL_MAX_CONN", "10"))


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            settings.redis.dsn(),
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=3.0,
            health_check_interval=30,
            single_connection_client=_SINGLE_CONN,
            **({} if _SINGLE_CONN else {"max_connections": _MAX_CONNECTIONS}),
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
