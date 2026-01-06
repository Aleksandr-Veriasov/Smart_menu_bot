import uuid
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis


async def acquire_lock(r: Redis, name: str, ttl: int = 10) -> str | None:
    token = str(uuid.uuid4())
    ok = await r.set(name, token, nx=True, ex=ttl)
    return token if ok else None


async def release_lock(r: Redis, name: str, token: str) -> None:
    # атомарно снимаем лок только владельцем
    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
      return redis.call('DEL', KEYS[1])
    else return 0 end
    """
    await cast("Awaitable[Any]", r.eval(script, 1, name, token))
