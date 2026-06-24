import json
import logging

from packages.redis.repository.base import BaseRedisRepository

logger = logging.getLogger(__name__)


class RecipeCacheRepository(BaseRedisRepository):

    async def get_recipe_count(self, user_id: int) -> int | None:
        """Вернёт количество рецептов пользователя из Redis или None, если кэша нет."""
        raw = await self.redis.get(self.keys.recipe_count(user_id=user_id))
        return int(raw) if raw is not None else None

    async def set_recipe_count(self, user_id: int, count: int) -> None:
        """Сохраняет количество рецептов пользователя в Redis с TTL."""
        count_ttl = self.ttl.RECIPE_COUNT_SHORT if count < 5 else self.ttl.RECIPE_COUNT_LONG
        await self.redis.setex(self.keys.recipe_count(user_id=user_id), count_ttl, str(count))

    async def invalidate_recipe_count(self, user_id: int) -> None:
        """Удаляет кэш количества рецептов пользователя."""
        await self.redis.delete(self.keys.recipe_count(user_id=user_id))

    async def get_all_by_user_and_category(self, user_id: int, category_id: int) -> list[dict[str, int | str]] | None:
        """Вернёт список (id, title) всех рецептов пользователя из Redis или None, если кэша нет."""
        raw = await self.redis.get(self.keys.user_recipes_ids_and_titles(user_id, category_id))
        logger.debug(f"👉 Строка для Redis: {raw}")
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, list) and all(isinstance(x, dict) for x in data):
                return data
        except Exception:
            pass
        return None

    async def set_all_recipes_ids_and_titles(
        self,
        user_id: int,
        category_id: int,
        items: list[dict[str, int | str]],
    ) -> None:
        """Сохраняет список (id, title) всех рецептов пользователя в Redis с TTL."""
        payload = json.dumps(items, ensure_ascii=False)
        await self.redis.setex(
            self.keys.user_recipes_ids_and_titles(user_id, category_id),
            self.ttl.USER_RECIPES_IDS_AND_TITLES,
            payload,
        )

    async def invalidate_all_recipes_ids_and_titles(self, user_id: int, category_id: int) -> None:
        """Удаляет кэш списка (id, title) всех рецептов пользователя."""
        await self.redis.delete(self.keys.user_recipes_ids_and_titles(user_id, category_id))
        logger.debug(f"❌ Удален кэш рецептов пользователя {user_id}")
