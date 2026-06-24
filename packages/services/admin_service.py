from packages.db.repository import BroadcastRepository, RecipeRepository, UserRepository
from packages.schemas.admin import AdminStatsRead
from packages.services.base import BaseService


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

        return AdminStatsRead(
            users_count=users_count,
            recipes_count=recipes_count,
            broadcasts_count=broadcasts_count,
            active_broadcasts_count=active_broadcasts_count,
        )
