from collections.abc import Iterable
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from packages.db.models import RecipeIngredient

from .base import BaseRepository


class IngredientLink:
    """Данные для создания/обновления связи рецепт-ингредиент."""

    __slots__ = ("ingredient_id", "quantity", "unit")

    def __init__(
        self,
        ingredient_id: int,
        quantity: Decimal | None = None,
        unit: str | None = None,
    ) -> None:
        self.ingredient_id = ingredient_id
        self.quantity = quantity
        self.unit = unit


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
        links: Iterable[IngredientLink],
    ) -> None:
        """Массово создаёт или обновляет связи рецепт-ингредиент.

        При конфликте по (recipe_id, ingredient_id) обновляет quantity и unit.
        Принимает Iterable[IngredientLink]; дубликаты по ingredient_id схлопываются
        (побеждает последний в итерируемом).
        """
        seen: dict[int, IngredientLink] = {}
        for link in links:
            if link.ingredient_id:
                seen[int(link.ingredient_id)] = link

        if not seen:
            return

        values = [
            {
                "recipe_id": int(recipe_id),
                "ingredient_id": link.ingredient_id,
                "quantity": link.quantity,
                "unit": link.unit,
            }
            for link in seen.values()
        ]
        stmt = (
            pg_insert(self.model)
            .values(values)
            .on_conflict_do_update(
                index_elements=[self.model.recipe_id, self.model.ingredient_id],
                set_={"quantity": pg_insert(self.model).excluded.quantity, "unit": pg_insert(self.model).excluded.unit},
            )
        )
        await self.session.execute(stmt)

    async def get_links_for_recipe(self, recipe_id: int) -> list[RecipeIngredient]:
        """Возвращает связи рецепт-ингредиент с qty/unit и именем ингредиента."""
        stmt = (
            sa.select(RecipeIngredient)
            .where(RecipeIngredient.recipe_id == recipe_id)
            .options(joinedload(RecipeIngredient.ingredient))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_link_ids(
        self,
        recipe_id: int,
        ingredient_ids: Iterable[int],
    ) -> None:
        """Легаси-метод: принимает только ids, quantity/unit остаются NULL.

        Используется в WebApp write-path до перехода на IngredientLink.
        """
        links = [IngredientLink(ingredient_id=int(i)) for i in ingredient_ids if i]
        await self.bulk_link(recipe_id, links)
