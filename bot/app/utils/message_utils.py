import logging
import random
from html import escape

from redis.asyncio import Redis

from bot.app.services.category_service import CategoryService
from bot.app.services.recipe_service import RecipeService
from packages.db.database import Database
from packages.db.repository import RecipeRepository, VideoRepository

# Включаем логирование
logger = logging.getLogger(__name__)


async def random_recipe(db: Database, redis: Redis, user_id: int, category_slug: str) -> tuple[str | None, str]:
    """
    Получает случайный рецепт из категории для пользователя.
    """
    service_cat = CategoryService(db, redis)
    category_id, category_name = await service_cat.get_id_and_name_by_slug_cached(category_slug)
    service_rec = RecipeService(db, redis)
    recipes = await service_rec.get_all_recipes_ids_and_titles(user_id, category_id)
    recipes_ids = [recipe["id"] for recipe in recipes]
    random_recipe_id = random.choice(recipes_ids)
    async with db.session() as session:
        recipe = await RecipeRepository().get_recipe_with_connections(session, int(random_recipe_id))
        if recipe is None:
            return "", ""
        else:
            video_url = await VideoRepository().get_video_url(session, int(recipe.id))
            await RecipeRepository.update_last_used_at(session, int(recipe.id))
            await session.commit()
            logger.debug("◀️ %s - video URL для рецепта %s", video_url, recipe.title)
            # Формируем список ингредиентов
            safe_category_name = escape(category_name or "")
            safe_title = escape(recipe.title or "")
            safe_description = escape(recipe.description or "")
            ingredients_text = "\n".join(f"- {escape(ingredient.name or '')}" for ingredient in recipe.ingredients)
            text = (
                f'Вот случайный рецепт из категории "{safe_category_name}":\n\n'
                f"🍽 <b>Название рецепта:</b> {safe_title}\n\n"
                f"📝 <b>Рецепт:</b>\n{safe_description}\n\n"
                f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
            )
            return video_url, text
