"""Тесты для CategoryRepository."""

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
    UserCreate,
)


class TestCategoryRepositoryCreate:
    """Тесты для CategoryRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_category_basic(self, db_session: AsyncSession) -> None:
        """Создание базовой категории (slug генерируется автоматически)."""
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Завтраки"),
        )

        assert category.id is not None
        assert category.name == "Завтраки"

    @pytest.mark.asyncio
    async def test_create_categories_with_same_name(self, db_session: AsyncSession) -> None:
        """Можно создавать категории с одинаковыми именами."""
        cat1 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты"),
        )
        cat2 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты"),
        )

        assert cat1.id != cat2.id
        assert cat1.name == cat2.name

    @pytest.mark.asyncio
    async def test_create_multiple_categories(self, db_session: AsyncSession) -> None:
        """Создание нескольких категорий."""
        cat1 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Категория 1"),
        )
        cat2 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Категория 2"),
        )

        assert cat1.id is not None
        assert cat2.id is not None
        assert cat1.id != cat2.id


class TestCategoryRepositoryGet:
    """Тесты для методов получения категорий."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_slug_raises_error(self, db_session: AsyncSession) -> None:
        """Получение по несуществующему slug вызывает ValueError."""
        with pytest.raises(ValueError, match="Category not found"):
            await CategoryRepository.get_id_and_name_by_slug(db_session, "nonexistent")

    @pytest.mark.asyncio
    async def test_get_id_by_nonexistent_slug_raises_error(self, db_session: AsyncSession) -> None:
        """Получение ID по несуществующему slug вызывает ValueError."""
        with pytest.raises(ValueError, match="Category not found"):
            await CategoryRepository.get_id_by_slug(db_session, "nonexistent")

    @pytest.mark.asyncio
    async def test_get_all(self, db_session: AsyncSession) -> None:
        """Получение всех категорий."""
        # Создаем несколько категорий
        cat1 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Категория 1", slug="cat-1"),
        )
        cat2 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Категория 2", slug="cat-2"),
        )

        all_categories = await CategoryRepository.get_all(db_session)

        assert len(all_categories) >= 2
        ids = [c["id"] for c in all_categories]
        assert cat1.id in ids
        assert cat2.id in ids

    @pytest.mark.asyncio
    async def test_get_all_name_and_slug(self, db_session: AsyncSession) -> None:
        """Получение имен и слагов всех категорий."""
        await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Салаты"),
        )
        await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Супы"),
        )

        results = await CategoryRepository.get_all_name_and_slug(db_session)

        assert len(results) >= 2
        names = [r["name"] for r in results]
        assert "Салаты" in names
        assert "Супы" in names

    @pytest.mark.asyncio
    async def test_get_name_and_slug_by_user_id(self, db_session: AsyncSession) -> None:
        """Получение категорий пользователя."""
        # Создаем пользователя
        user = await UserRepository.create(
            db_session,
            UserCreate(id=111111, username="user_with_recipes"),
        )

        # Создаем категории
        cat1 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Основные"),
        )
        cat2 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Закуски"),
        )

        # Создаем рецепты в этих категориях
        await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 1",
                user_id=user.id,
                category_id=cat1.id,
            ),
        )
        await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 2",
                user_id=user.id,
                category_id=cat2.id,
            ),
        )

        # Получаем категории пользователя
        user_categories = await CategoryRepository.get_name_and_slug_by_user_id(db_session, user.id)

        assert len(user_categories) == 2
        names = [c["name"] for c in user_categories]
        assert "Основные" in names
        assert "Закуски" in names

    @pytest.mark.asyncio
    async def test_get_name_and_slug_by_user_id_no_recipes(self, db_session: AsyncSession) -> None:
        """Получение категорий для пользователя без рецептов."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=222222, username="user_no_recipes"),
        )

        user_categories = await CategoryRepository.get_name_and_slug_by_user_id(db_session, user.id)

        assert user_categories == []


class TestCategoryRepositoryIntegration:
    """Интеграционные тесты для CategoryRepository."""

    @pytest.mark.asyncio
    async def test_category_with_multiple_users(self, db_session: AsyncSession) -> None:
        """Одна категория может быть связана с несколькими пользователями."""
        # Создаем категорию
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Общая"),
        )

        # Создаем двух пользователей
        user1 = await UserRepository.create(
            db_session,
            UserCreate(id=333333, username="user1"),
        )
        user2 = await UserRepository.create(
            db_session,
            UserCreate(id=444444, username="user2"),
        )

        # Создаем рецепты обоих пользователей в одной категории
        await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт пользователя 1",
                user_id=user1.id,
                category_id=category.id,
            ),
        )
        await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт пользователя 2",
                user_id=user2.id,
                category_id=category.id,
            ),
        )

        # Проверяем что оба пользователя видят категорию
        cats_user1 = await CategoryRepository.get_name_and_slug_by_user_id(db_session, user1.id)
        cats_user2 = await CategoryRepository.get_name_and_slug_by_user_id(db_session, user2.id)

        assert len(cats_user1) == 1
        assert len(cats_user2) == 1
        assert cats_user1[0]["name"] == "Общая"
        assert cats_user2[0]["name"] == "Общая"

    @pytest.mark.asyncio
    async def test_get_all_returns_proper_structure(self, db_session: AsyncSession) -> None:
        """get_all возвращает словари с id, name, slug."""
        await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Проверка структуры"),
        )

        all_cats = await CategoryRepository.get_all(db_session)

        # Проверяем структуру
        for cat in all_cats:
            assert "id" in cat
            assert "name" in cat
            assert "slug" in cat
            assert isinstance(cat["id"], int)
            assert isinstance(cat["name"], str)
