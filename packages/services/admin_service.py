from packages.db.repository import BroadcastRepository, RecipeRepository, UserRepository
from packages.redis.keys import RedisKeys
from packages.redis.ttl import USER_EXISTS
from packages.schemas.admin import AdminStatsRead
from packages.services.base import BaseService

_1H = 60 * 60
_12H = 12 * _1H


class AdminService(BaseService):
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
