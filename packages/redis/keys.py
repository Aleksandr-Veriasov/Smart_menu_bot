from packages.common_settings.settings import settings


class RedisKeys:
    PREFIX = settings.redis.prefix

    @classmethod
    def user_exists(cls, user_id: int | str) -> str:
        return f"{cls.PREFIX}:user:{user_id}:exists"

    @classmethod
    def recipe_count(cls, user_id: int | str) -> str:
        return f"{cls.PREFIX}:user:{user_id}:recipe_count"

    @classmethod
    def user_init_lock(cls, user_id: int | str) -> str:
        return f"{cls.PREFIX}:lock:user_init:{user_id}"

    @classmethod
    def user_categories(cls, user_id: int | str) -> str:
        return f"{cls.PREFIX}:user:{int(user_id)}:categories"

    @classmethod
    def category_by_slug(cls, slug: str) -> str:
        return f"{cls.PREFIX}:category:by_slug:{slug}"

    @classmethod
    def slug_init_lock(cls, slug: int | str) -> str:
        return f"{cls.PREFIX}:lock:slug_init:{slug}"

    @classmethod
    def all_category(cls) -> str:
        return f"{cls.PREFIX}:categories:all"

    @classmethod
    def catergory_lock(cls) -> str:
        return f"{cls.PREFIX}:lock:category"

    @classmethod
    def user_recipes_ids_and_titles(cls, user_id: int | str, category_id: int | str) -> str:
        return f"{cls.PREFIX}:user:{user_id}:category" f":{category_id}:recipes_ids_titles"

    @classmethod
    def user_last_recipe_messages(cls, user_id: int | str) -> str:
        return f"{cls.PREFIX}:user:{user_id}:last_recipe_messages"
