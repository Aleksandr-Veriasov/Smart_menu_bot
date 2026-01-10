import inspect
import uuid
from collections.abc import Awaitable
from typing import TypeVar

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
    await _maybe_await(r.eval(script, 1, name, token))


T = TypeVar("T")


async def _maybe_await(value: Awaitable[T] | T) -> T:
    if inspect.isawaitable(value):
        return await value
    return value
