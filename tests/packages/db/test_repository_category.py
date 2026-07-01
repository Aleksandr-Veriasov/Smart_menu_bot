"""Тесты для CategoryRepository."""

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Category
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

    async def test_create_category_basic(self, db_session: AsyncSession) -> None:
        """Создание базовой категории (slug генерируется автоматически)."""
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Завтраки"),
        )

        assert category.id is not None
        assert category.name == "Завтраки"

    async def test_create_categories_with_same_name(self, db_session: AsyncSession) -> None:
        """Можно создавать категории с одинаковыми именами."""
        repo = CategoryRepository(db_session)
        cat1 = await repo.create(
            CategoryCreate(name="Рецепты"),
        )
        cat2 = await repo.create(
            CategoryCreate(name="Рецепты"),
        )

        assert cat1.id != cat2.id
        assert cat1.name == cat2.name

    async def test_create_multiple_categories(self, db_session: AsyncSession) -> None:
        """Создание нескольких категорий."""
        repo = CategoryRepository(db_session)
        cat1 = await repo.create(
            CategoryCreate(name="Категория 1"),
        )
        cat2 = await repo.create(
            CategoryCreate(name="Категория 2"),
        )

        assert cat1.id is not None
        assert cat2.id is not None
        assert cat1.id != cat2.id


class TestCategoryRepositoryGet:
    """Тесты для методов получения категорий."""

    async def test_get_by_nonexistent_slug_returns_none(self, db_session: AsyncSession) -> None:
        """Получение по несуществующему slug возвращает None."""
        result = await CategoryRepository(db_session).get_by_slug("nonexistent")
        assert result is None

    async def test_get_by_slug(self, db_session: AsyncSession) -> None:
        """Получение категории по slug."""
        obj = Category(name="Салаты", slug="salads")
        db_session.add(obj)
        await db_session.flush()
        await db_session.refresh(obj)

        category = await CategoryRepository(db_session).get_by_slug("salads")
        assert category is not None
        assert category.id == obj.id
        assert category.name == "Салаты"
        assert category.slug == "salads"

    async def test_get_all(self, db_session: AsyncSession) -> None:
        """Получение всех категорий."""
        repo = CategoryRepository(db_session)
        # Создаем несколько категорий
        cat1 = await repo.create(
            CategoryCreate(name="Категория 1", slug="cat-1"),
        )
        cat2 = await repo.create(
            CategoryCreate(name="Категория 2", slug="cat-2"),
        )

        all_categories = await repo.get_all()

        assert len(all_categories) >= 2
        ids = [c.id for c in all_categories]
        assert cat1.id in ids
        assert cat2.id in ids

    async def test_get_by_user_id(self, db_session: AsyncSession) -> None:
        """Получение категорий пользователя."""
        # Создаем пользователя
        user = await UserRepository(db_session).create(
            UserCreate(id=111111, username="user_with_recipes"),
        )

        # Создаем категории
        cat_repo = CategoryRepository(db_session)
        cat1 = await cat_repo.create(
            CategoryCreate(name="Основные"),
        )
        cat2 = await cat_repo.create(
            CategoryCreate(name="Закуски"),
        )

        # Создаем рецепты в этих категориях
        recipe_repo = RecipeRepository(db_session)
        await recipe_repo.create(
            RecipeCreate(
                title="Рецепт 1",
                user_id=user.id,
                category_id=cat1.id,
            ),
        )
        await recipe_repo.create(
            RecipeCreate(
                title="Рецепт 2",
                user_id=user.id,
                category_id=cat2.id,
            ),
        )

        # Получаем категории пользователя
        user_categories = await cat_repo.get_by_user_id(user.id)

        assert len(user_categories) == 2
        names = [c.name for c in user_categories]
        assert "Основные" in names
        assert "Закуски" in names

    async def test_get_by_user_id_no_recipes(self, db_session: AsyncSession) -> None:
        """Получение категорий для пользователя без рецептов."""
        user = await UserRepository(db_session).create(
            UserCreate(id=222222, username="user_no_recipes"),
        )

        user_categories = await CategoryRepository(db_session).get_by_user_id(user.id)

        assert user_categories == []


class TestCategoryRepositoryIntegration:
    """Интеграционные тесты для CategoryRepository."""

    async def test_category_with_multiple_users(self, db_session: AsyncSession) -> None:
        """Одна категория может быть связана с несколькими пользователями."""
        cat_repo = CategoryRepository(db_session)
        user_repo = UserRepository(db_session)
        recipe_repo = RecipeRepository(db_session)

        # Создаем категорию
        category = await cat_repo.create(
            CategoryCreate(name="Общая"),
        )

        # Создаем двух пользователей
        user1 = await user_repo.create(
            UserCreate(id=333333, username="user1"),
        )
        user2 = await user_repo.create(
            UserCreate(id=444444, username="user2"),
        )

        # Создаем рецепты обоих пользователей в одной категории
        await recipe_repo.create(
            RecipeCreate(
                title="Рецепт пользователя 1",
                user_id=user1.id,
                category_id=category.id,
            ),
        )
        await recipe_repo.create(
            RecipeCreate(
                title="Рецепт пользователя 2",
                user_id=user2.id,
                category_id=category.id,
            ),
        )

        # Проверяем что оба пользователя видят категорию
        cats_user1 = await cat_repo.get_by_user_id(user1.id)
        cats_user2 = await cat_repo.get_by_user_id(user2.id)

        assert len(cats_user1) == 1
        assert len(cats_user2) == 1
        assert cats_user1[0].name == "Общая"
        assert cats_user2[0].name == "Общая"

    async def test_get_all_returns_proper_structure(self, db_session: AsyncSession) -> None:
        """get_all возвращает словари с id, name, slug."""
        repo = CategoryRepository(db_session)
        await repo.create(
            CategoryCreate(name="Проверка структуры"),
        )

        all_cats = await repo.get_all()

        for cat in all_cats:
            assert isinstance(cat.id, int)
            assert isinstance(cat.name, str)
