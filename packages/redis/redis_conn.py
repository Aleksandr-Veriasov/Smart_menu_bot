from __future__ import annotations

from redis.asyncio import Redis

from packages.common_settings.settings import settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            settings.redis.dsn(),
            encoding="utf-8",
            decode_responses=True,  # удобно для строк/JSON
            socket_timeout=5.0,
            socket_connect_timeout=3.0,
            health_check_interval=30,
            single_connection_client=False,  # пул
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
