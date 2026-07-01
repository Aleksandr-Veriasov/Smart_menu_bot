"""Тесты bulk_link с quantity/unit и on_conflict_do_update."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import RecipeIngredient
from packages.db.repository import (
    CategoryRepository,
    IngredientRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    UserRepository,
)
from packages.db.schemas import CategoryCreate, RecipeCreate, UserCreate
from packages.schemas.recipe import IngredientLink


@pytest.fixture
async def recipe_with_ingredient(db_session: AsyncSession):
    """Создаёт пользователя, категорию, рецепт и один ингредиент."""
    user = await UserRepository(db_session).create(UserCreate(id=21000001, username="qty_user1"))
    category = await CategoryRepository(db_session).create(CategoryCreate(name="qty_cat1"))
    recipe = await RecipeRepository(db_session).create(
        RecipeCreate(title="qty_recipe1", user_id=user.id, category_id=category.id)
    )
    ingredient = await IngredientRepository(db_session).create("мука_qty")
    return recipe, ingredient


class TestBulkLinkWithQty:

    async def test_saves_quantity_and_unit(self, db_session: AsyncSession, recipe_with_ingredient):
        """bulk_link сохраняет quantity и unit в junction-таблице."""
        recipe, ingredient = recipe_with_ingredient
        link = IngredientLink(ingredient_id=ingredient.id, quantity=Decimal("200"), unit="г")

        await RecipeIngredientRepository(db_session).bulk_link(recipe.id, [link])

        row = await db_session.scalar(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe.id,
                RecipeIngredient.ingredient_id == ingredient.id,
            )
        )
        assert row is not None
        assert row.quantity == Decimal("200")
        assert row.unit == "г"

    async def test_null_quantity_and_unit(self, db_session: AsyncSession, recipe_with_ingredient):
        """bulk_link без qty/unit сохраняет NULL."""
        recipe, ingredient = recipe_with_ingredient
        link = IngredientLink(ingredient_id=ingredient.id)

        await RecipeIngredientRepository(db_session).bulk_link(recipe.id, [link])

        row = await db_session.scalar(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe.id,
                RecipeIngredient.ingredient_id == ingredient.id,
            )
        )
        assert row is not None
        assert row.quantity is None
        assert row.unit is None

    async def test_conflict_updates_qty_unit(self, db_session: AsyncSession, recipe_with_ingredient):
        """При повторном bulk_link quantity и unit обновляются (on_conflict_do_update)."""
        recipe, ingredient = recipe_with_ingredient
        repo = RecipeIngredientRepository(db_session)

        await repo.bulk_link(
            recipe.id, [IngredientLink(ingredient_id=ingredient.id, quantity=Decimal("100"), unit="г")]
        )
        await repo.bulk_link(
            recipe.id, [IngredientLink(ingredient_id=ingredient.id, quantity=Decimal("250"), unit="мл")]
        )

        row = await db_session.scalar(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe.id,
                RecipeIngredient.ingredient_id == ingredient.id,
            )
        )
        assert row.quantity == Decimal("250")
        assert row.unit == "мл"

    async def test_empty_list_no_error(self, db_session: AsyncSession, recipe_with_ingredient):
        """Пустой список — ничего не происходит, ошибки нет."""
        recipe, _ = recipe_with_ingredient
        await RecipeIngredientRepository(db_session).bulk_link(recipe.id, [])

        rows = (
            (await db_session.execute(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)))
            .scalars()
            .all()
        )
        assert rows == []

    async def test_zero_ingredient_id_skipped(self, db_session: AsyncSession, recipe_with_ingredient):
        """IngredientLink с ingredient_id=0 игнорируется."""
        recipe, ingredient = recipe_with_ingredient
        repo = RecipeIngredientRepository(db_session)

        await repo.bulk_link(
            recipe.id,
            [
                IngredientLink(ingredient_id=0),
                IngredientLink(ingredient_id=ingredient.id, quantity=Decimal("1"), unit="шт"),
            ],
        )

        rows = (
            (await db_session.execute(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].ingredient_id == ingredient.id

    async def test_duplicates_last_wins(self, db_session: AsyncSession, recipe_with_ingredient):
        """Дублирующиеся ingredient_id в одном вызове — побеждает последний."""
        recipe, ingredient = recipe_with_ingredient

        await RecipeIngredientRepository(db_session).bulk_link(
            recipe.id,
            [
                IngredientLink(ingredient_id=ingredient.id, quantity=Decimal("100"), unit="г"),
                IngredientLink(ingredient_id=ingredient.id, quantity=Decimal("999"), unit="кг"),
            ],
        )

        row = await db_session.scalar(
            select(RecipeIngredient).where(
                RecipeIngredient.recipe_id == recipe.id,
                RecipeIngredient.ingredient_id == ingredient.id,
            )
        )
        assert row.quantity == Decimal("999")
        assert row.unit == "кг"

    async def test_multiple_ingredients(self, db_session: AsyncSession, recipe_with_ingredient):
        """Несколько ингредиентов с разными qty/unit сохраняются корректно."""
        recipe, _ = recipe_with_ingredient
        ing_repo = IngredientRepository(db_session)
        ing1 = await ing_repo.create("соль_qty")
        ing2 = await ing_repo.create("масло_qty")
        ing3 = await ing_repo.create("перец_qty")

        links = [
            IngredientLink(ingredient_id=ing1.id, quantity=Decimal("1"), unit="ч.л."),
            IngredientLink(ingredient_id=ing2.id, quantity=Decimal("50"), unit="мл"),
            IngredientLink(ingredient_id=ing3.id),
        ]
        await RecipeIngredientRepository(db_session).bulk_link(recipe.id, links)

        rows = {
            r.ingredient_id: r
            for r in (await db_session.execute(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id)))
            .scalars()
            .all()
        }
        assert rows[ing1.id].unit == "ч.л."
        assert rows[ing2.id].quantity == Decimal("50")
        assert rows[ing3.id].quantity is None
