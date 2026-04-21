"""Тесты для RecipeRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import (
    CategoryRepository,
    RecipeRepository,
    UserRepository,
)
from packages.db.schemas import (
    CategoryCreate,
    RecipeCreate,
    RecipeUpdate,
    UserCreate,
)


class TestRecipeRepositoryCreateBasic:
    """Тесты для RecipeRepository.create_basic()."""

    @pytest.mark.asyncio
    async def test_create_basic_recipe(self, db_session: AsyncSession) -> None:
        """Создание базового рецепта с названием и описанием."""
        recipe = await RecipeRepository.create_basic(
            db_session, title="Паста Болоньезе", description="Классический итальянский соус"
        )

        assert recipe.id is not None
        assert recipe.title == "Паста Болоньезе"
        assert recipe.description == "Классический итальянский соус"

    @pytest.mark.asyncio
    async def test_create_basic_without_description(self, db_session: AsyncSession) -> None:
        """Создание рецепта без описания."""
        recipe = await RecipeRepository.create_basic(db_session, title="Омлет", description=None)

        assert recipe.id is not None
        assert recipe.title == "Омлет"
        assert recipe.description is None

    @pytest.mark.asyncio
    async def test_create_basic_empty_title(self, db_session: AsyncSession) -> None:
        """Создание рецепта с пустым названием."""
        recipe = await RecipeRepository.create_basic(db_session, title="", description="Описание без названия")

        assert recipe.id is not None
        assert recipe.title == ""


class TestRecipeRepositoryCreate:
    """Тесты для RecipeRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_recipe_with_user_and_category(self, db_session: AsyncSession) -> None:
        """Создание рецепта с привязкой к пользователю и категории."""
        # Создаем пользователя
        user = await UserRepository.create(db_session, UserCreate(id=123456, username="testuser"))

        # Создаем категорию
        category = await CategoryRepository.create(db_session, CategoryCreate(name="Завтраки", slug="breakfasts"))

        # Создаем рецепт
        recipe_create = RecipeCreate(
            title="Омлет с беконом",
            description="Вкусный омлет",
            user_id=user.id,
            category_id=category.id,
        )
        recipe = await RecipeRepository.create(db_session, recipe_create)

        assert recipe.id is not None
        assert recipe.title == "Омлет с беконом"
        assert recipe.description == "Вкусный омлет"

    @pytest.mark.asyncio
    async def test_create_recipe_requires_user_and_category(self, db_session: AsyncSession) -> None:
        """RecipeCreate требует обязательные user_id и category_id."""
        from pydantic_core import ValidationError

        with pytest.raises(ValidationError):
            RecipeCreate(  # type: ignore[call-arg]
                title="Рецепт без связей",
                description="Это должно вызвать ошибку",
            )


class TestRecipeRepositoryUpdate:
    """Тесты для RecipeRepository.update()."""

    @pytest.mark.asyncio
    async def test_update_recipe_title(self, db_session: AsyncSession) -> None:
        """Обновление названия рецепта."""
        # Создаем рецепт
        recipe = await RecipeRepository.create_basic(db_session, title="Старое название", description="Описание")

        # Обновляем
        updated = await RecipeRepository.update(db_session, recipe.id, RecipeUpdate(title="Новое название"))

        assert updated.title == "Новое название"
        assert updated.description == "Описание"  # не изменилось

    @pytest.mark.asyncio
    async def test_update_recipe_description(self, db_session: AsyncSession) -> None:
        """Обновление описания рецепта."""
        recipe = await RecipeRepository.create_basic(db_session, title="Рецепт", description="Старое описание")

        updated = await RecipeRepository.update(db_session, recipe.id, RecipeUpdate(description="Новое описание"))

        assert updated.description == "Новое описание"
        assert updated.title == "Рецепт"

    @pytest.mark.asyncio
    async def test_update_nonexistent_recipe_raises_error(self, db_session: AsyncSession) -> None:
        """Обновление несуществующего рецепта вызывает ValueError."""
        with pytest.raises(ValueError, match="Recipe not found"):
            await RecipeRepository.update(db_session, 999999, RecipeUpdate(title="Новое название"))


class TestRecipeRepositoryGet:
    """Тесты для методов получения рецептов."""

    @pytest.mark.asyncio
    async def test_get_name_by_id(self, db_session: AsyncSession) -> None:
        """Получение названия рецепта по ID."""
        recipe = await RecipeRepository.create_basic(
            db_session, title="Паста Карбонара", description="Итальянское блюдо"
        )

        name = await RecipeRepository.get_name_by_id(db_session, recipe.id)

        assert name == "Паста Карбонара"

    @pytest.mark.asyncio
    async def test_get_name_by_nonexistent_id(self, db_session: AsyncSession) -> None:
        """Получение названия несуществующего рецепта возвращает None."""
        name = await RecipeRepository.get_name_by_id(db_session, 999999)

        assert name is None

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession) -> None:
        """Получение рецепта по ID."""
        recipe = await RecipeRepository.create_basic(db_session, title="Салат Цезарь", description="С курицей")

        retrieved = await RecipeRepository.get_by_id(db_session, recipe.id)

        assert retrieved is not None
        assert retrieved.id == recipe.id
        assert retrieved.title == "Салат Цезарь"

    @pytest.mark.asyncio
    async def test_get_nonexistent_recipe_returns_none(self, db_session: AsyncSession) -> None:
        """Получение несуществующего рецепта возвращает None."""
        result = await RecipeRepository.get_by_id(db_session, 999999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_count_by_user(self, db_session: AsyncSession) -> None:
        """Получение количества рецептов пользователя."""
        user = await UserRepository.create(db_session, UserCreate(id=345678, username="user3"))
        category = await CategoryRepository.create(db_session, CategoryCreate(name="Обеды", slug="lunches"))

        # Создаем несколько рецептов
        for i in range(3):
            await RecipeRepository.create(
                db_session,
                RecipeCreate(
                    title=f"Рецепт {i}",
                    user_id=user.id,
                    category_id=category.id,
                ),
            )

        count = await RecipeRepository.get_count_by_user(db_session, user.id)

        assert count == 3

    @pytest.mark.asyncio
    async def test_get_count_by_user_no_recipes(self, db_session: AsyncSession) -> None:
        """Получение количества рецептов для пользователя без рецептов."""
        user = await UserRepository.create(db_session, UserCreate(id=456789, username="user4"))

        count = await RecipeRepository.get_count_by_user(db_session, user.id)

        assert count == 0


class TestRecipeRepositoryDelete:
    """Тесты для RecipeRepository.delete()."""

    @pytest.mark.asyncio
    async def test_delete_recipe(self, db_session: AsyncSession) -> None:
        """Удаление рецепта."""
        recipe = await RecipeRepository.create_basic(
            db_session, title="Рецепт для удаления", description="Будет удален"
        )

        await RecipeRepository.delete(db_session, recipe.id)
        await db_session.flush()

        # Проверяем что рецепт удален
        retrieved = await RecipeRepository.get_by_id(db_session, recipe.id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_recipe_raises_error(self, db_session: AsyncSession) -> None:
        """Удаление несуществующего рецепта вызывает ValueError."""
        with pytest.raises(ValueError, match="Recipe not found"):
            await RecipeRepository.delete(db_session, 999999)


class TestRecipeRepositoryIntegration:
    """Интеграционные тесты для RecipeRepository."""

    @pytest.mark.asyncio
    async def test_full_recipe_lifecycle(self, db_session: AsyncSession) -> None:
        """Полный цикл жизни рецепта: создание, получение, обновление."""
        user = await UserRepository.create(db_session, UserCreate(id=567890, username="user5"))
        category = await CategoryRepository.create(db_session, CategoryCreate(name="Ужины", slug="dinners"))

        # Создание
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Первоначальное название",
                description="Первоначальное описание",
                user_id=user.id,
                category_id=category.id,
            ),
        )
        assert recipe.id is not None

        # Получение
        retrieved = await RecipeRepository.get_by_id(db_session, recipe.id)
        assert retrieved is not None
        assert retrieved.title == "Первоначальное название"

        # Обновление
        updated = await RecipeRepository.update(
            db_session, recipe.id, RecipeUpdate(title="Обновленное название", description="Обновленное описание")
        )
        assert updated.title == "Обновленное название"

        # Финальная проверка
        final = await RecipeRepository.get_by_id(db_session, recipe.id)
        assert final is not None
        assert final.title == "Обновленное название"
        assert final.description == "Обновленное описание"
