import inspect
import logging
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TypeVar

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def maybe_await(value: Awaitable[T] | T) -> T:
    """Если value awaitable, дожидается результата, иначе возвращает как есть."""
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True, slots=True)
class RedisLock:
    key: str
    token: str


class RedisLockRepository:
    """
    Атомарный distributed lock поверх Redis (token-based ownership).
    """

    @classmethod
    async def acquire(
        cls,
        r: Redis | None,
        *,
        key: str,
        ttl_sec: int,
        token: str | None = None,
    ) -> RedisLock | None:
        resolved_token = token or str(uuid.uuid4())
        if r is None:
            # Best-effort режим для single-process.
            return RedisLock(key=key, token=resolved_token)
        ok = await r.set(key, resolved_token, ex=int(ttl_sec), nx=True)
        return RedisLock(key=key, token=resolved_token) if ok else None

    @classmethod
    async def refresh(cls, r: Redis | None, lock: RedisLock, *, ttl_sec: int) -> bool:
        if r is None:
            return True
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
          return redis.call("expire", KEYS[1], tonumber(ARGV[2]))
        else
          return 0
        end
        """
        try:
            res = await maybe_await(r.eval(script, 1, lock.key, lock.token, str(int(ttl_sec))))
            return bool(res)
        except Exception:
            logger.exception("Redis lock refresh failed for key=%s", lock.key)
            return False

    @classmethod
    async def release(cls, r: Redis | None, lock: RedisLock) -> None:
        if r is None:
            return
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
          return redis.call("del", KEYS[1])
        else
          return 0
        end
        """
        try:
            await maybe_await(r.eval(script, 1, lock.key, lock.token))
        except Exception:
            logger.exception("Redis lock release failed for key=%s", lock.key)
