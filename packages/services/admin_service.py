from packages.db.repository import (
    AdminRepository,
    BroadcastRepository,
    RecipeRepository,
    UserRepository,
)
from packages.redis.keys import RedisKeys
from packages.redis.ttl import USER_EXISTS
from packages.schemas.admin import AdminStatsRead
from packages.security.passwords import verify_password
from packages.services.base import BaseService

_1H = 60 * 60
_12H = 12 * _1H


class AdminService(BaseService):
    async def authenticate(self, login: str, password: str) -> bool:
        """Проверить логин и пароль администратора."""
        async with self.db.session() as session:
            admin = await AdminRepository(session).get_by_login(login)
        if not admin:
            return False
        return verify_password(password, str(admin.password_hash))

    async def get_stats(self) -> AdminStatsRead:
        """Вернуть агрегированную статистику по пользователям, рецептам и рассылкам."""
        async with self.db.session() as session:
            users_count = await UserRepository(session).count()
            recipes_count = await RecipeRepository(session).count()
            try:
                broadcasts_count = await BroadcastRepository(session).count()
                active_broadcasts_count = await BroadcastRepository(session).count_running()
            except Exception:
                broadcasts_count = 0
                active_broadcasts_count = 0

        active_1h, active_12h, active_1d = await self._count_active_users()

        return AdminStatsRead(
            users_count=users_count,
            recipes_count=recipes_count,
            broadcasts_count=broadcasts_count,
            active_broadcasts_count=active_broadcasts_count,
            active_1h=active_1h,
            active_12h=active_12h,
            active_1d=active_1d,
        )

    # ── Admin panel: Redis keys ───────────────────────────────────────────────

    async def list_redis_keys_page(self, page: int, per_page: int) -> tuple[list[tuple[str, int]], int, bool]:
        """Вернуть список (key, ttl) для страницы, total_keys и has_more."""
        start = (page - 1) * per_page
        cursor = 0
        skipped = 0
        collected: list[bytes] = []
        has_more = False

        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, count=per_page)
            if keys:
                if skipped < start:
                    if skipped + len(keys) <= start:
                        skipped += len(keys)
                        keys = []
                    else:
                        keys = keys[start - skipped :]
                        skipped = start
                if keys:
                    needed = per_page - len(collected)
                    collected.extend(keys[:needed])
                    if len(keys) > needed:
                        has_more = True
                        break
            if cursor == 0:
                break
            if len(collected) >= per_page:
                has_more = True
                break

        key_names = sorted(
            k.decode("utf-8", errors="replace") if isinstance(k, bytes | bytearray) else str(k) for k in collected
        )
        total_keys = await self.redis.dbsize()

        ttls: list[int] = []
        if key_names:
            pipe = self.redis.pipeline()
            for k in key_names:
                pipe.ttl(k)
            ttls = await pipe.execute()

        return list(zip(key_names, ttls, strict=False)), int(total_keys), has_more

    async def get_redis_key_value(self, key: str) -> tuple[bool, str]:
        """Вернуть (missing, value) для ключа."""
        raw = await self.redis.get(key)
        if raw is None:
            return True, ""
        value = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes | bytearray) else str(raw)
        return False, value

    async def delete_redis_key(self, key: str) -> None:
        """Удалить ключ из Redis."""
        await self.redis.delete(key)

    async def _count_active_users(self) -> tuple[int, int, int]:
        """Подсчёт активных уников через TTL ключей user:*:exists.

        Момент последней активности: last_active = now - (USER_EXISTS_TTL - remaining_ttl).
        """
        pattern = RedisKeys.user_exists("*")
        c1h = c12h = c1d = 0
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=200)
            if keys:
                pipe = self.redis.pipeline(transaction=False)
                for k in keys:
                    pipe.ttl(k)
                ttls = await pipe.execute()
                for remaining in ttls:
                    if remaining <= 0:
                        continue
                    elapsed = USER_EXISTS - remaining
                    c1d += 1
                    if elapsed <= _12H:
                        c12h += 1
                    if elapsed <= _1H:
                        c1h += 1
            if cursor == 0:
                break
        return c1h, c12h, c1d
