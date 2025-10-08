from __future__ import annotations

from packages.common_settings.settings import settings


class RedisKeys:

    @staticmethod
    def _ns(key: str) -> str:
        """ Возвращает ключ с префиксом из настроек. """
        return settings.redis.namespaced(key)

    @classmethod
    def user_exists(cls, user_id: int | str) -> str:
        return cls._ns(f'user:{user_id}:exists')

    @classmethod
    def recipe_count(cls, user_id: int | str) -> str:
        return cls._ns(f'user:{user_id}:recipe_count')

    @classmethod
    def user_init_lock(cls, user_id: int | str) -> str:
        return cls._ns(f'lock:user_init:{user_id}')

    @classmethod
    def user_categories(cls, user_id: int | str) -> str:
        return cls._ns(f'user:{int(user_id)}:categories')

    @classmethod
    def category_by_slug(cls, slug: str) -> str:
        return cls._ns(f'category:by_slug:{slug}')

    @classmethod
    def slug_init_lock(cls, slug: int | str) -> str:
        return cls._ns(f'lock:slug_init:{slug}')

    @classmethod
    def all_category(cls) -> str:
        return cls._ns('categories:all')

    @classmethod
    def catergory_lock(cls) -> str:
        return cls._ns('lock:category')

    @classmethod
    def user_recipes_ids_and_titles(
        cls, user_id: int | str, category_id: int | str
    ) -> str:
        return (cls._ns(
            f'user:{user_id}:category:{category_id}:recipes_ids_titles'
        ))
