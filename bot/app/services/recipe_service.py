import logging
from contextlib import suppress
from dataclasses import dataclass, field

from redis.asyncio import Redis

from packages.db.database import Database
from packages.db.models import Recipe, Video
from packages.db.repository import (
    RecipeRepository,
    RecipeUserRepository,
    VideoRepository,
)
from packages.redis import ttl
from packages.redis.keys import RedisKeys
from packages.redis.lock_repository import RedisLockRepository
from packages.redis.repository import CategoryCacheRepository, RecipeCacheRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExistingRecipeMatch:
    """Результат поиска уже сохранённого рецепта по исходному URL видео."""

    recipe_ids: list[int] = field(default_factory=list)  # уникальные кандидаты в порядке появления
    video_url: str | None = None  # url первого видео (для single-match)
    recipe: Recipe | None = None  # загруженный рецепт (для single-match)
    already_linked: bool = False  # уже сохранён у текущего пользователя


def _collect_recipe_candidates(videos: list[Video]) -> tuple[Video | None, list[int]]:
    """Первое валидное видео и уникальные recipe_id в порядке появления."""
    first_video: Video | None = None
    recipe_ids: list[int] = []
    seen: set[int] = set()
    for video in videos:
        recipe_id = getattr(video, "recipe_id", None)
        if not recipe_id:
            continue
        if first_video is None:
            first_video = video
        if recipe_id in seen:
            continue
        seen.add(recipe_id)
        recipe_ids.append(recipe_id)
    return first_video, recipe_ids


class RecipeService:
    def __init__(self, db: Database, redis: Redis):
        self.db = db
        self.redis = redis

    async def get_all_recipes_ids_and_titles(self, user_id: int, category_id: int) -> list[dict[str, int | str]]:
        """
        Получить все id и названия рецептов пользователя.
        """
        # 1) пробуем Redis
        cached = await RecipeCacheRepository.get_all_recipes_ids_and_titles(self.redis, user_id, category_id)
        logger.debug(f"👉 Пользователь: {user_id} категория: {category_id} " f"название рецептов и id: {cached}")
        if cached:
            return cached

        # 2) БД
        lock_key = RedisKeys.user_init_lock(user_id=user_id)
        lock = await RedisLockRepository.acquire(self.redis, key=lock_key, ttl_sec=ttl.LOCK)
        try:
            async with self.db.session() as self.session:
                rows = await RecipeRepository.get_all_recipes_ids_and_titles(self.session, user_id, category_id)
                await RecipeCacheRepository.set_all_recipes_ids_and_titles(self.redis, user_id, category_id, rows)
        finally:
            if lock:
                with suppress(Exception):
                    await RedisLockRepository.release(self.redis, lock)
        logger.debug(f"👉 Пользователь: {user_id} категория: {category_id} " f"название рецептов и id из БД: {rows}")
        return rows

    async def get_public_recipes_ids_and_titles(
        self, category_id: int, *, exclude_user_id: int | None = None
    ) -> list[dict[str, int | str]]:
        """Публичные рецепты категории (книга рецептов), кроме рецептов пользователя."""
        async with self.db.session() as session:
            return await RecipeRepository.get_public_recipes_ids_and_titles_by_category(
                session, category_id, exclude_user_id=exclude_user_id
            )

    async def get_recipe_for_view(self, recipe_id: int) -> Recipe | None:
        """Рецепт со связями для показа карточки; попутно отмечает last_used_at."""
        async with self.db.session() as session:
            recipe = await RecipeRepository.get_recipe_with_connections(session, recipe_id)
            if recipe:
                await RecipeRepository.update_last_used_at(session, int(recipe.id))
            return recipe

    async def get_recipe_with_details(self, recipe_id: int) -> Recipe | None:
        """Рецепт со связями без отметки last_used_at (для просмотра по шаринг-ссылке)."""
        async with self.db.session() as session:
            return await RecipeRepository.get_recipe_with_connections(session, recipe_id)

    async def get_recipe_basic(self, recipe_id: int) -> Recipe | None:
        """Рецепт без связей (название/описание)."""
        async with self.db.session() as session:
            return await RecipeRepository.get_by_id(session, recipe_id)

    async def find_existing_by_url(self, url: str, user_id: int | None, *, limit: int) -> ExistingRecipeMatch:
        """Ищет уже сохранённый рецепт по исходному URL видео.

        Для одиночного совпадения сразу грузит рецепт со связями и проверяет,
        привязан ли он к пользователю. Для нескольких — возвращает только
        список кандидатов (выбор делает отдельный сценарий).
        """
        async with self.db.session() as session:
            videos = await VideoRepository.get_all_by_original_url(session, url, limit=limit)
            if not videos:
                return ExistingRecipeMatch()

            first_video, recipe_ids = _collect_recipe_candidates(videos)
            if not first_video or not recipe_ids:
                return ExistingRecipeMatch()

            # Несколько кандидатов — рецепт не грузим, отдаём список наверх.
            if len(recipe_ids) >= 2:
                return ExistingRecipeMatch(recipe_ids=recipe_ids)

            recipe = await RecipeRepository.get_recipe_with_connections(session, first_video.recipe_id)
            if not recipe:
                logger.warning("Рецепт recipe_id=%s не найден для video_id=%s", first_video.recipe_id, first_video.id)
                return ExistingRecipeMatch()

            already_linked = False
            if user_id:
                already_linked = await RecipeUserRepository.is_linked(session, recipe.id, user_id)

            return ExistingRecipeMatch(
                recipe_ids=recipe_ids,
                video_url=first_video.video_url,
                recipe=recipe,
                already_linked=already_linked,
            )

    async def get_titles_for_ids(self, recipe_ids: list[int]) -> list[tuple[int, str]]:
        """Пары (id, title) только для существующих рецептов, в порядке переданных id."""
        async with self.db.session() as session:
            rows = await RecipeRepository.get_ids_and_titles_by_ids(session, [int(x) for x in recipe_ids])
        id_to_title = {int(row["id"]): str(row["title"]) for row in rows}
        return [(int(rid), id_to_title[int(rid)]) for rid in recipe_ids if int(rid) in id_to_title]

    async def get_recipe_with_link_status(self, recipe_id: int, user_id: int) -> tuple[Recipe | None, bool]:
        """Рецепт со связями + флаг, привязан ли он к пользователю."""
        async with self.db.session() as session:
            recipe = await RecipeRepository.get_recipe_with_connections(session, recipe_id)
            if not recipe:
                return None, False
            already_linked = await RecipeUserRepository.is_linked(session, recipe_id, user_id)
            return recipe, already_linked

    async def link_recipe_to_user(self, recipe_id: int, user_id: int, category_id: int) -> bool:
        """Привязывает рецепт к пользователю/категории и инвалидирует кэш.

        Возвращает True, если связь создана; False — если уже была (обновили категорию).
        """
        async with self.db.session() as session:
            created = await RecipeUserRepository.upsert_user_link(session, recipe_id, user_id, category_id)
        await CategoryCacheRepository.invalidate_user_categories(self.redis, user_id)
        await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(self.redis, user_id, category_id)
        return created

    async def search_by_title(self, user_id: int, query: str) -> list[dict[str, int | str]]:
        """Поиск рецептов пользователя по названию."""
        async with self.db.session() as session:
            return await RecipeRepository.search_ids_and_titles_by_title(session, user_id, query)

    async def search_by_ingredient(self, user_id: int, query: str) -> list[dict[str, int | str]]:
        """Поиск рецептов пользователя по ингредиенту."""
        async with self.db.session() as session:
            return await RecipeRepository.search_ids_and_titles_by_ingredient(session, user_id, query)

    async def get_recipe_name(self, recipe_id: int) -> str | None:
        """Название рецепта по id."""
        async with self.db.session() as session:
            return await RecipeRepository.get_name_by_id(session, recipe_id)

    async def delete_recipe(self, user_id: int, recipe_id: int) -> None:
        """Удаляет связь рецепт-пользователь и инвалидирует кэш."""
        async with self.db.session() as session:
            category_id = await RecipeRepository.get_category_id_by_recipe_id(session, recipe_id, user_id)
            logger.debug(f"👉 Рецепт {recipe_id} category_id: {category_id}")
            await RecipeUserRepository.unlink_user(session, recipe_id, user_id)
        if category_id is not None:
            await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(self.redis, user_id, category_id)
            # Обновляем кэш рецептов
            await self.get_all_recipes_ids_and_titles(user_id=user_id, category_id=category_id)

    async def update_recipe_title(self, user_id: int, recipe_id: int, new_title: str) -> None:
        """Обновляет название рецепта и инвалидирует кэш."""
        async with self.db.session() as session:
            category_id = await RecipeRepository.get_category_id_by_recipe_id(session, recipe_id, user_id)
            logger.debug(f"👉 Рецепт {recipe_id} category_id: {category_id}")
            await RecipeRepository.update_title(session, recipe_id, new_title)
        if category_id is not None:
            await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(self.redis, user_id, category_id)
            # Обновляем кэш рецептов
            await self.get_all_recipes_ids_and_titles(user_id=user_id, category_id=category_id)
