from collections.abc import Iterable
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from packages.db.models import RecipeIngredient
from packages.schemas.recipe import IngredientLink
from packages.schemas.webapp import IngredientItemWrite

from .base import BaseRepository
from .ingredient import IngredientRepository


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

    async def get_link(
        self, recipe_id: int, ingredient_id: int, *, with_ingredient: bool = False
    ) -> RecipeIngredient | None:
        """Найти связь рецепт-ингредиент; опционально с joinedload ингредиента."""
        stmt = sa.select(self.model).where(
            self.model.recipe_id == recipe_id,
            self.model.ingredient_id == ingredient_id,
        )
        if with_ingredient:
            stmt = stmt.options(joinedload(self.model.ingredient))
        return await self.session.scalar(stmt)

    async def update_link(
        self, recipe_id: int, ingredient_id: int, *, quantity: Decimal | None, unit: str | None
    ) -> RecipeIngredient | None:
        """Обновить qty/unit связи рецепт-ингредиент. Вернуть None если связь не найдена."""
        link = await self.get_link(recipe_id, ingredient_id)
        if link is None:
            return None
        link.quantity = quantity
        link.unit = unit
        await self.session.flush()
        return link

    async def delete_link(self, recipe_id: int, ingredient_id: int) -> None:
        """Удалить связь рецепт-ингредиент."""
        await self.session.execute(
            sa.delete(self.model).where(
                self.model.recipe_id == recipe_id,
                self.model.ingredient_id == ingredient_id,
            )
        )

    async def save_from_names(self, recipe_id: int, names: list[str]) -> None:
        """Создать/найти ингредиенты по именам и привязать к рецепту."""
        if not names:
            return
        id_by_name = await IngredientRepository(self.session).bulk_get_or_create(names)
        await self.bulk_link_ids(recipe_id, id_by_name.values())

    async def save_from_structured(self, recipe_id: int, items: list[IngredientItemWrite]) -> None:
        """Создать/найти ингредиенты из структурированного списка (name, quantity, unit) и привязать к рецепту."""
        names = [item.name for item in items if item.name]
        if not names:
            return
        id_by_name = await IngredientRepository(self.session).bulk_get_or_create(names)
        links = [
            IngredientLink(ingredient_id=id_by_name[item.name], quantity=item.quantity, unit=item.unit)
            for item in items
            if item.name and item.name in id_by_name
        ]
        await self.bulk_link(recipe_id, links)

    async def delete_all_by_recipe(self, recipe_id: int) -> None:
        """Удалить все ингредиенты рецепта."""
        await self.session.execute(sa.delete(self.model).where(self.model.recipe_id == int(recipe_id)))

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
