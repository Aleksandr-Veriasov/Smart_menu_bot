import logging
import random
from collections.abc import Iterable
from dataclasses import dataclass, field

from packages.db.models import Recipe, Video
from packages.db.repository import (
    IngredientRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    RecipeUserRepository,
    VideoRepository,
)
from packages.db.schemas import RecipeShort
from packages.redis.repository import CategoryCacheRepository, RecipeCacheRepository
from packages.services.base import BaseService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExistingRecipeMatch:
    """Результат поиска уже сохранённого рецепта по исходному URL видео."""

    recipe_ids: list[int] = field(default_factory=list)  # уникальные кандидаты в порядке появления
    video_url: str | None = None  # url первого видео (для single-match)
    recipe: Recipe | None = None  # загруженный рецепт (для single-match)
    already_linked: bool = False  # уже сохранён у текущего пользователя


class RecipeService(BaseService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recipe_cache = RecipeCacheRepository(self.redis)
        self.category_cache = CategoryCacheRepository(self.redis)
        self.recipe_repo = RecipeRepository
        self.recipe_user_repo = RecipeUserRepository
        self.video_repo = VideoRepository
        self.ingredient_repo = IngredientRepository
        self.recipe_ingredient_repo = RecipeIngredientRepository

    async def get_all_by_user_and_category(self, user_id: int, category_id: int) -> list[RecipeShort]:
        """Все id и названия рецептов пользователя."""
        cached = await self.recipe_cache.get_all_by_user_and_category(user_id, category_id)
        logger.debug(f"👉 Пользователь: {user_id} категория: {category_id} " f"название рецептов и id: {cached}")
        if cached:
            return [RecipeShort.model_validate(r) for r in cached]

        async with self._lock(self.keys.user_init_lock(user_id=user_id)):
            async with self.db.session() as session:
                recipes = await self.recipe_repo(session).get_all_by_user_and_category(user_id, category_id)
                result = [RecipeShort.model_validate(r) for r in recipes]
                await self.recipe_cache.set_all_recipes_ids_and_titles(
                    user_id, category_id, [r.model_dump() for r in result]
                )
        logger.debug(f"👉 Пользователь: {user_id} категория: {category_id} " f"название рецептов и id из БД: {result}")
        return result

    async def get_book_recipes(self, category_id: int, *, exclude_user_id: int | None = None) -> list[RecipeShort]:
        """Публичные рецепты категории (книга рецептов), кроме рецептов пользователя."""
        async with self.db.session() as session:
            recipes = await self.recipe_repo(session).get_public_recipes_by_category(
                category_id, exclude_user_id=exclude_user_id
            )
        return [RecipeShort.model_validate(r) for r in recipes]

    async def get_recipe_for_view(self, recipe_id: int) -> Recipe | None:
        """Рецепт со связями для показа карточки; попутно отмечает last_used_at."""
        async with self.db.session() as session:
            repo = self.recipe_repo(session)
            recipe = await repo.get_recipe_with_connections(recipe_id)
            if recipe:
                await repo.update_last_used_at(int(recipe.id))
            return recipe

    async def get_recipe_with_details(self, recipe_id: int) -> Recipe | None:
        """Рецепт со связями без отметки last_used_at (для просмотра по шаринг-ссылке)."""
        async with self.db.session() as session:
            return await self.recipe_repo(session).get_recipe_with_connections(recipe_id)

    async def get_recipe_basic(self, recipe_id: int) -> Recipe | None:
        """Рецепт без связей (название/описание)."""
        async with self.db.session() as session:
            return await self.recipe_repo(session).get_by_id(recipe_id)

    async def find_existing_by_url(self, url: str, user_id: int | None, *, limit: int) -> ExistingRecipeMatch:
        """Ищет уже сохранённый рецепт по исходному URL видео.

        Для одиночного совпадения сразу грузит рецепт со связями и проверяет,
        привязан ли он к пользователю. Для нескольких — возвращает только
        список кандидатов (выбор делает отдельный сценарий).
        """
        async with self.db.session() as session:
            videos = await self.video_repo(session).get_all_by_original_url(url, limit=limit)
            if not videos:
                return ExistingRecipeMatch()

            first_video, recipe_ids = self._collect_recipe_candidates(videos)
            if not first_video or not recipe_ids:
                return ExistingRecipeMatch()

            # Несколько кандидатов — рецепт не грузим, отдаём список наверх.
            if len(recipe_ids) >= 2:
                return ExistingRecipeMatch(recipe_ids=recipe_ids)

            recipe_repo = self.recipe_repo(session)
            recipe = await recipe_repo.get_recipe_with_connections(first_video.recipe_id)
            if not recipe:
                logger.warning("Рецепт recipe_id=%s не найден для video_id=%s", first_video.recipe_id, first_video.id)
                return ExistingRecipeMatch()

            already_linked = False
            if user_id:
                already_linked = await self.recipe_user_repo(session).is_linked(recipe.id, user_id)

            return ExistingRecipeMatch(
                recipe_ids=recipe_ids,
                video_url=first_video.video_url,
                recipe=recipe,
                already_linked=already_linked,
            )

    async def get_titles_for_ids(self, recipe_ids: list[int]) -> list[RecipeShort]:
        """Рецепты (id + title) для переданных id, в порядке их появления."""
        async with self.db.session() as session:
            recipes = await self.recipe_repo(session).get_recipes(recipe_ids)
        by_id = {r.id: RecipeShort.model_validate(r) for r in recipes}
        return [by_id[rid] for rid in recipe_ids if rid in by_id]

    async def get_recipe_with_link_status(self, recipe_id: int, user_id: int) -> tuple[Recipe | None, bool]:
        """Рецепт со связями + флаг, привязан ли он к пользователю."""
        async with self.db.session() as session:
            recipe = await self.recipe_repo(session).get_recipe_with_connections(recipe_id)
            if not recipe:
                return None, False
            already_linked = await self.recipe_user_repo(session).is_linked(recipe_id, user_id)
            return recipe, already_linked

    async def link_recipe_to_user(self, recipe_id: int, user_id: int, category_id: int) -> bool:
        """Привязывает рецепт к пользователю/категории и инвалидирует кэш.

        Возвращает True, если связь создана; False — если уже была (обновили категорию).
        """
        async with self.db.session() as session:
            created = await self.recipe_user_repo(session).upsert_user_link(recipe_id, user_id, category_id)
        await self.category_cache.invalidate_user_categories(user_id)
        await self.recipe_cache.invalidate_recipe_count(user_id)
        await self.recipe_cache.invalidate_all_recipes_ids_and_titles(user_id, category_id)
        return created

    async def search_by_title(self, user_id: int, query: str) -> list[RecipeShort]:
        """Поиск рецептов пользователя по названию."""
        async with self.db.session() as session:
            recipes = await self.recipe_repo(session).search_recipes_by_title(user_id, query)
        return [RecipeShort.model_validate(r) for r in recipes]

    async def search_by_ingredient(self, user_id: int, query: str) -> list[RecipeShort]:
        """Поиск рецептов пользователя по ингредиенту."""
        async with self.db.session() as session:
            recipes = await self.recipe_repo(session).search_recipes_by_ingredient(user_id, query)
        return [RecipeShort.model_validate(r) for r in recipes]

    async def get_recipe_name(self, recipe_id: int) -> str | None:
        """Название рецепта по id."""
        async with self.db.session() as session:
            return await self.recipe_repo(session).get_name_by_id(recipe_id)

    async def delete_recipe(self, user_id: int, recipe_id: int) -> None:
        """Удаляет связь рецепт-пользователь и инвалидирует кэш."""
        async with self.db.session() as session:
            category_id = await self.recipe_repo(session).get_category_id_by_recipe_id(recipe_id, user_id)
            logger.debug(f"👉 Рецепт {recipe_id} category_id: {category_id}")
            await self.recipe_user_repo(session).unlink_user(recipe_id, user_id)
        if category_id is not None:
            await self.recipe_cache.invalidate_all_recipes_ids_and_titles(user_id, category_id)
            # Обновляем кэш рецептов
            await self.get_all_by_user_and_category(user_id=user_id, category_id=category_id)

    async def get_random_recipe(self, user_id: int, category_id: int) -> Recipe | None:
        """Возвращает случайный рецепт пользователя из категории."""
        recipes = await self.get_all_by_user_and_category(user_id, category_id)
        if not recipes:
            return None
        recipe_id = random.choice(recipes).id
        return await self.get_recipe_for_view(recipe_id)

    async def save_recipe_draft(
        self,
        *,
        title: str,
        description: str | None,
        ingredients: str | Iterable[object],
        video_url: str | None = None,
        original_url: str | None = None,
    ) -> int:
        """Сохраняет черновик рецепта без привязки к пользователю и категории."""
        from packages.recipes_core.ingredients_parser import (
            parse_ingredients,
            to_ingredient_name,
        )

        ingredients_raw = parse_ingredients(ingredients) if isinstance(ingredients, str) else list(ingredients)
        async with self.db.session() as session:
            recipe = await self.recipe_repo(session).create_basic(
                title=title,
                description=description or "Не указано",
            )
            names = [n for n in (to_ingredient_name(x) for x in ingredients_raw) if n]
            id_by_name = await self.ingredient_repo(session).bulk_get_or_create(names)
            await self.recipe_ingredient_repo(session).bulk_link(int(recipe.id), id_by_name.values())
            if video_url:
                await self.video_repo(session).create(video_url, int(recipe.id), original_url=original_url)
            return int(recipe.id)

    async def update_recipe_title(self, user_id: int, recipe_id: int, new_title: str) -> None:
        """Обновляет название рецепта и инвалидирует кэш."""
        async with self.db.session() as session:
            repo = self.recipe_repo(session)
            category_id = await repo.get_category_id_by_recipe_id(recipe_id, user_id)
            logger.debug(f"👉 Рецепт {recipe_id} category_id: {category_id}")
            await repo.update_title(recipe_id, new_title)
        if category_id is not None:
            await self.recipe_cache.invalidate_all_recipes_ids_and_titles(user_id, category_id)
            # Обновляем кэш рецептов
            await self.get_all_by_user_and_category(user_id=user_id, category_id=category_id)

    @staticmethod
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
