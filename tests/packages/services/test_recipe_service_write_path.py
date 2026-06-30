"""Регрессионные тесты write-path save_recipe_draft: structured vs legacy."""

from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Ingredient, Recipe, RecipeIngredient
from packages.recipes_core.deepseek_parsers import IngredientItem
from packages.services.recipe_service import RecipeService


def make_service(session: AsyncSession) -> RecipeService:
    """Создаёт RecipeService, проксирующий db.session() в тестовую сессию."""
    db = MagicMock()

    @asynccontextmanager
    async def _session_ctx():
        yield session

    db.session.side_effect = _session_ctx
    redis = MagicMock()
    return RecipeService(db=db, redis=redis)


async def _get_links(session: AsyncSession, recipe_id: int) -> list[RecipeIngredient]:
    result = await session.execute(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id))
    return list(result.scalars().all())


class TestSaveRecipeDraftStructured:

    async def test_structured_saves_qty_and_unit(self, db_session: AsyncSession):
        """list[IngredientItem] → quantity и unit сохраняются в junction-таблице."""
        service = make_service(db_session)
        items = [
            IngredientItem(name="мука", quantity=Decimal("200"), unit="г"),
            IngredientItem(name="молоко", quantity=Decimal("0.5"), unit="л"),
        ]
        recipe_id = await service.save_recipe_draft(
            title="Блины structured",
            description="Описание",
            ingredients=items,
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        by_name = {(await db_session.get(Ingredient, link.ingredient_id)).name: link for link in links}
        assert by_name["мука"].quantity == Decimal("200")
        assert by_name["мука"].unit == "г"
        assert by_name["молоко"].quantity == Decimal("0.5")
        assert by_name["молоко"].unit == "л"

    async def test_structured_null_qty_unit(self, db_session: AsyncSession):
        """IngredientItem без qty/unit → NULL в БД (не ошибка)."""
        service = make_service(db_session)
        items = [IngredientItem(name="соль")]
        recipe_id = await service.save_recipe_draft(
            title="Блины null qty",
            description=None,
            ingredients=items,
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        assert len(links) == 1
        assert links[0].quantity is None
        assert links[0].unit is None

    async def test_structured_creates_ingredients_on_the_fly(self, db_session: AsyncSession):
        """Ингредиенты создаются через bulk_get_or_create если их нет в БД."""
        service = make_service(db_session)
        items = [IngredientItem(name="новый_ингр_xyz", quantity=Decimal("3"), unit="шт")]
        recipe_id = await service.save_recipe_draft(
            title="Новый рецепт",
            description=None,
            ingredients=items,
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        assert len(links) == 1

        ing = await db_session.get(Ingredient, links[0].ingredient_id)
        assert ing is not None
        assert ing.name == "новый_ингр_xyz"

    async def test_structured_empty_list(self, db_session: AsyncSession):
        """Пустой список IngredientItem → рецепт создаётся, связей нет."""
        service = make_service(db_session)
        recipe_id = await service.save_recipe_draft(
            title="Без ингредиентов",
            description=None,
            ingredients=[],
        )
        await db_session.commit()

        recipe = await db_session.get(Recipe, recipe_id)
        assert recipe is not None
        links = await _get_links(db_session, recipe_id)
        assert links == []


class TestSaveRecipeDraftLegacy:

    async def test_legacy_string_saves_names_only(self, db_session: AsyncSession):
        """Строка с маркерами '- ' → ингредиенты сохраняются, qty/unit = NULL."""
        service = make_service(db_session)
        recipe_id = await service.save_recipe_draft(
            title="Борщ легаси",
            description=None,
            ingredients="- Свёкла\n- Капуста\n- Морковь",
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        assert len(links) == 3
        for link in links:
            assert link.quantity is None
            assert link.unit is None

    async def test_legacy_list_of_strings(self, db_session: AsyncSession):
        """list[str] → ингредиенты сохраняются, qty/unit = NULL."""
        service = make_service(db_session)
        recipe_id = await service.save_recipe_draft(
            title="Суп легаси",
            description=None,
            ingredients=["Картошка", "Лук", "Морковь"],
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        assert len(links) == 3

    async def test_legacy_empty_string(self, db_session: AsyncSession):
        """Пустая строка → рецепт создаётся, связей нет."""
        service = make_service(db_session)
        recipe_id = await service.save_recipe_draft(
            title="Пустой легаси",
            description=None,
            ingredients="",
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        assert links == []


class TestSaveRecipeDraftRegression:

    async def test_structured_does_not_fall_back_to_legacy(self, db_session: AsyncSession):
        """list[IngredientItem] → не использует legacy-путь, qty сохраняется."""
        service = make_service(db_session)
        items = [IngredientItem(name="масло", quantity=Decimal("50"), unit="мл")]
        recipe_id = await service.save_recipe_draft(
            title="Регрессия",
            description=None,
            ingredients=items,
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        assert len(links) == 1
        assert links[0].quantity == Decimal("50")
        assert links[0].unit == "мл"

    async def test_legacy_does_not_save_qty(self, db_session: AsyncSession):
        """Легаси-путь никогда не сохраняет qty — это регрессионная проверка."""
        service = make_service(db_session)
        recipe_id = await service.save_recipe_draft(
            title="Легаси без qty",
            description=None,
            ingredients=["Перец"],
        )
        await db_session.commit()

        links = await _get_links(db_session, recipe_id)
        assert len(links) == 1
        assert links[0].quantity is None
