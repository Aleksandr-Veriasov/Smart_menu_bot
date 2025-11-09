import json
import logging
from typing import Dict, List, Optional, Tuple

from redis.asyncio import Redis

from packages.redis import ttl
from packages.redis.keys import RedisKeys

logger = logging.getLogger(__name__)


class UserCacheRepository:

    @classmethod
    async def get_exists(cls, r: Redis, user_id: int) -> bool | None:
        """
        Проверить наличие флага 'пользователь существует'.
        Возвращает:
          - True, если флаг есть
          - None, если ключа нет
        """
        raw = await r.get(RedisKeys.user_exists(user_id=user_id))
        return True if raw is not None else None

    @classmethod
    async def set_exists(cls, r: Redis, user_id: int) -> None:
        """
        Установить флаг 'пользователь существует'.
        """
        await r.setex(
            RedisKeys.user_exists(user_id=user_id),
            ttl.USER_EXISTS,
            '1'
        )
        logger.debug(f'✅ User {user_id} exists set in cache')

    @classmethod
    async def invalidate_exists(cls, r: Redis, user_id: int) -> None:
        """
        Удалить флаг 'пользователь существует'.
        """
        await r.delete(RedisKeys.user_exists(user_id=user_id))


class RecipeCacheRepository:

    @classmethod
    async def get_recipe_count(cls, r: Redis, user_id: int) -> int | None:
        """
        Вернёт количество рецептов пользователя из Redis
        или None, если кэша нет.
        """
        raw = await r.get(RedisKeys.recipe_count(user_id=user_id))
        return int(raw) if raw is not None else None

    @classmethod
    async def set_recipe_count(
        cls, r: Redis, user_id: int, count: int
    ) -> None:
        """ Сохраняет количество рецептов пользователя в Redis с TTL. """
        count_ttl = (
            ttl.RECIPE_COUNT_SHORT if count < 5 else ttl.RECIPE_COUNT_LONG
        )
        await r.setex(RedisKeys.recipe_count(
            user_id=user_id
        ), count_ttl, str(count))

    @classmethod
    async def invalidate_recipe_count(cls, r: Redis, user_id: int) -> None:
        """ Удаляет кэш количества рецептов пользователя. """
        await r.delete(RedisKeys.recipe_count(user_id=user_id))

    @classmethod
    async def get_all_recipes_ids_and_titles(
        cls, r: Redis, user_id: int, category_id: int
    ) -> Optional[List[dict[str, int | str]]]:
        """
        Вернёт список (id, title) всех рецептов пользователя из Redis
        или None, если кэша нет.
        """
        raw = await r.get(
            RedisKeys.user_recipes_ids_and_titles(user_id, category_id)
        )
        logger.debug(f'👉 Raw from Redis: {raw}')
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            # лёгкая валидация формы
            if isinstance(data, list) and all(
                isinstance(x, dict) for x in data
            ):
                return data
        except Exception:
            # битые данные — игнорируем
            pass
        return None

    @classmethod
    async def set_all_recipes_ids_and_titles(
        cls, r: Redis, user_id: int, category_id: int,
        items: List[dict[str, int | str]]
    ) -> None:
        """
        Сохраняет список (id, title) всех рецептов пользователя в Redis с TTL.
        """
        payload = json.dumps(items, ensure_ascii=False)
        await r.setex(
            RedisKeys.user_recipes_ids_and_titles(user_id, category_id),
            ttl.USER_RECIPES_IDS_AND_TITLES,
            payload
        )

    @classmethod
    async def invalidate_all_recipes_ids_and_titles(
        cls, r: Redis, user_id: int, category_id: int
    ) -> None:
        """ Удаляет кэш списка (id, title) всех рецептов пользователя. """
        await r.delete(RedisKeys.user_recipes_ids_and_titles(
            user_id, category_id
        ))


class CategoryCacheRepository:

    @classmethod
    async def get_user_categories(
        cls, r: Redis, user_id: int
    ) -> Optional[List[Dict[str, str]]]:
        """
        Вернёт список словарей [{'name':..., 'slug':...}] из Redis
        или None, если кэша нет.
        """
        raw = await r.get(RedisKeys.user_categories(user_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            # лёгкая валидация формы
            if isinstance(data, list) and all(
                isinstance(x, dict) for x in data
            ):
                return data
        except Exception:
            # битые данные — игнорируем
            pass
        return None

    @classmethod
    async def set_user_categories(
        cls, r: Redis, user_id: int, items: List[Dict[str, str]]
    ) -> None:
        """ Сохраняет список категорий пользователя в Redis с TTL. """
        payload = json.dumps(items, ensure_ascii=False)
        await r.setex(
            RedisKeys.user_categories(user_id), ttl.USER_CATEGORIES, payload
        )

    @classmethod
    async def invalidate_user_categories(cls, r: Redis, user_id: int) -> None:
        """
        Удаляет кэш (используй при изменении категорий/рецептов пользователя).
        """
        await r.delete(RedisKeys.user_categories(user_id))

    @classmethod
    async def get_id_name_by_slug(
        cls, r: Redis, slug: str
    ) -> Optional[Tuple[int, str]]:
        """
        Вернёт (id, name) категории из Redis по slug
        или None, если кэша нет.
        """
        raw = await r.get(RedisKeys.category_by_slug(slug))
        if raw is None:
            return None
        # формат 'id|name'
        try:
            s_id, s_name = raw.split('|', 1)
            return int(s_id), s_name
        except Exception:
            # битые данные — подчистим
            await r.delete(RedisKeys.category_by_slug(slug))
            return None

    @classmethod
    async def set_id_name_by_slug(
        cls, r: Redis, slug: str, cat_id: int, name: str
    ) -> None:
        """ Сохраняет (id, name) категории в Redis по slug. """
        value = f'{int(cat_id)}|{name}'
        await r.set(RedisKeys.category_by_slug(slug), value)

    @classmethod
    async def invalidate_by_slug(cls, r: Redis, slug: str) -> None:
        """ Удаляет кэш категории по slug. """
        await r.delete(RedisKeys.category_by_slug(slug))

    @classmethod
    async def get_all_name_and_slug(
        cls, r: Redis
    ) -> Optional[List[Dict[str, str]]]:
        """
        Вернёт список словарей [{'name':..., 'slug':...}] всех категорий из
        Redis или None, если кэша нет.
        """
        raw = await r.get(RedisKeys.all_category())
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            # лёгкая валидация формы
            if isinstance(data, list) and all(
                isinstance(x, dict) for x in data
            ):
                return data
        except Exception:
            # битые данные — игнорируем
            await r.delete(RedisKeys.all_category())
            logger.debug(f'❌ Запись {RedisKeys.all_category()} битая, удалена')
            return None
        return None

    @classmethod
    async def set_all_name_and_slug(
        cls, r: Redis, items: List[Dict[str, str]]
    ) -> None:
        """ Сохраняет список всех категорий в Redis с TTL. """
        payload = json.dumps(items, ensure_ascii=False)
        await r.set(RedisKeys.all_category(), payload)
        logger.debug(f'✅ Запись {RedisKeys.all_category()} сохранена в кэш')

    @classmethod
    async def invalidate_all_name_and_slug(cls, r: Redis) -> None:
        """ Удаляет кэш всех категорий. """
        await r.delete(RedisKeys.all_category())
        logger.debug(f'❌ Запись {RedisKeys.all_category()} удалена из кэша')
