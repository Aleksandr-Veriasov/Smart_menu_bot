from collections.abc import Iterable

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from packages.db.models import RecipeIngredient

from .base import BaseRepository


class RecipeIngredientRepository(BaseRepository[RecipeIngredient]):
    """Репозиторий для связей рецепт-ингредиент."""

    model = RecipeIngredient

    async def create(self, recipe_id: int, ingredient_id: int) -> RecipeIngredient:
        """Создать связь рецепт-ингредиент. Raises ValueError при дублировании."""
        recipe_ingredient = self.model(recipe_id=recipe_id, ingredient_id=ingredient_id)
        self.session.add(recipe_ingredient)
        try:
            return await self.save(recipe_ingredient)
        except IntegrityError as exc:
            raise ValueError("RecipeIngredient already exists") from exc

    async def bulk_link(
        self,
        recipe_id: int,
        ingredient_ids: Iterable[int],
    ) -> None:
        """Массово создаёт связи рецепт-ингредиент. Дубликаты игнорируются."""
        ids = list({int(i) for i in ingredient_ids if i})
        if not ids:
            return
        values = [{"recipe_id": int(recipe_id), "ingredient_id": i} for i in ids]
        stmt = (
            pg_insert(self.model)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[
                    self.model.recipe_id,
                    self.model.ingredient_id,
                ]
            )
        )
        await self.session.execute(stmt)
