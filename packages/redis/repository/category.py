import json
import logging

from packages.redis.repository.base import BaseRedisRepository

logger = logging.getLogger(__name__)


class CategoryCacheRepository(BaseRedisRepository):

    async def get_user_categories(self, user_id: int) -> list[dict[str, int | str]] | None:
        """Вернёт список словарей [{'id':..., 'name':..., 'slug':...}] из Redis или None, если кэша нет."""
        raw = await self.redis.get(self.keys.user_categories(user_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, list) and all(isinstance(x, dict) for x in data):
                return data
        except Exception:
            pass
        return None

    async def set_user_categories(self, user_id: int, items: list[dict[str, int | str]]) -> None:
        """Сохраняет список категорий пользователя в Redis с TTL."""
        payload = json.dumps(items, ensure_ascii=False)
        await self.redis.setex(self.keys.user_categories(user_id), self.ttl.USER_CATEGORIES, payload)

    async def invalidate_user_categories(self, user_id: int) -> None:
        """Удаляет кэш категорий пользователя."""
        await self.redis.delete(self.keys.user_categories(user_id))

    async def get_id_name_by_slug(self, slug: str) -> tuple[int, str] | None:
        """Вернёт (id, name) категории из Redis по slug или None, если кэша нет."""
        raw = await self.redis.get(self.keys.category_by_slug(slug))
        if raw is None:
            return None
        try:
            s_id, s_name = raw.split("|", 1)
            return int(s_id), s_name
        except Exception:
            await self.redis.delete(self.keys.category_by_slug(slug))
            return None

    async def set_id_name_by_slug(self, slug: str, cat_id: int, name: str) -> None:
        """Сохраняет (id, name) категории в Redis по slug."""
        value = f"{int(cat_id)}|{name}"
        await self.redis.set(self.keys.category_by_slug(slug), value)

    async def invalidate_by_slug(self, slug: str) -> None:
        """Удаляет кэш категории по slug."""
        await self.redis.delete(self.keys.category_by_slug(slug))

    async def get_all_name_and_slug(self) -> list[dict[str, int | str]] | None:
        """Вернёт список словарей всех категорий из Redis или None, если кэша нет."""
        raw = await self.redis.get(self.keys.all_category())
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, list) and all(isinstance(x, dict) for x in data):
                return data
        except Exception:
            await self.redis.delete(self.keys.all_category())
            logger.debug(f"❌ Запись {self.keys.all_category()} битая, удалена")
            return None
        return None

    async def set_all_name_and_slug(self, items: list[dict[str, int | str]]) -> None:
        """Сохраняет список всех категорий в Redis с TTL."""
        payload = json.dumps(items, ensure_ascii=False)
        await self.redis.set(self.keys.all_category(), payload)
        logger.debug(f"✅ Запись {self.keys.all_category()} сохранена в кэш")

    async def invalidate_all_name_and_slug(self) -> None:
        """Удаляет кэш всех категорий."""
        await self.redis.delete(self.keys.all_category())
        logger.debug(f"❌ Запись {self.keys.all_category()} удалена из кэша")
