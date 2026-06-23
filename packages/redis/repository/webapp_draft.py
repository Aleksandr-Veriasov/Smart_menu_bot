import json

from packages.redis.repository.base import BaseRedisRepository


class WebAppRecipeDraftCacheRepository(BaseRedisRepository):
    """
    Короткоживущий черновик редактирования рецепта в Telegram WebApp.

    Используется для восстановления title/category при навигации между страницами WebApp.
    """

    async def get(self, *, user_id: int, recipe_id: int) -> dict | None:
        """Прочитать черновик (по возможности)."""
        key = self.keys.user_webapp_recipe_draft(int(user_id), int(recipe_id))
        raw = await self.redis.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def set_merge(
        self,
        *,
        user_id: int,
        recipe_id: int,
        title: str | None,
        category_id: int | None,
    ) -> dict:
        """
        Сохранить черновик, аккуратно мерджая поля.

        Правила:
        - пустое название не затирает уже сохранённое в черновике
        - невалидный/нулевой category_id не затирает уже сохранённый
        """
        key = self.keys.user_webapp_recipe_draft(int(user_id), int(recipe_id))
        prev = await self.get(user_id=int(user_id), recipe_id=int(recipe_id)) or {}

        next_title = prev.get("title")
        if title is not None:
            t = str(title).strip()
            if t:
                next_title = t

        next_category_id = prev.get("category_id")
        if category_id is not None:
            try:
                cid = int(category_id)
                if cid > 0:
                    next_category_id = cid
            except Exception:
                pass

        payload_dict = {"title": next_title, "category_id": next_category_id}
        payload = json.dumps(payload_dict, ensure_ascii=False)
        await self.redis.setex(key, int(self.ttl.WEBAPP_RECIPE_DRAFT), payload)
        return payload_dict

    async def clear(self, *, user_id: int, recipe_id: int) -> None:
        """Удалить черновик."""
        await self.redis.delete(self.keys.user_webapp_recipe_draft(int(user_id), int(recipe_id)))
