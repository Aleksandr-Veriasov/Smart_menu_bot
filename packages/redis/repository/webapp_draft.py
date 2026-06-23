import json

from redis.asyncio import Redis

from packages.redis import ttl
from packages.redis.keys import RedisKeys


class WebAppRecipeDraftCacheRepository:
    """
    Короткоживущий черновик редактирования рецепта в Telegram WebApp.

    Используется для восстановления title/category при навигации между страницами WebApp.
    """

    @classmethod
    async def get(cls, r: Redis, *, user_id: int, recipe_id: int) -> dict | None:
        """Прочитать черновик (по возможности)."""
        key = RedisKeys.user_webapp_recipe_draft(int(user_id), int(recipe_id))
        raw = await r.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @classmethod
    async def set_merge(
        cls,
        r: Redis,
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
        key = RedisKeys.user_webapp_recipe_draft(int(user_id), int(recipe_id))
        prev = await cls.get(r, user_id=int(user_id), recipe_id=int(recipe_id)) or {}

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
        await r.setex(key, int(ttl.WEBAPP_RECIPE_DRAFT), payload)
        return payload_dict

    @classmethod
    async def clear(cls, r: Redis, *, user_id: int, recipe_id: int) -> None:
        """Удалить черновик."""
        await r.delete(RedisKeys.user_webapp_recipe_draft(int(user_id), int(recipe_id)))
