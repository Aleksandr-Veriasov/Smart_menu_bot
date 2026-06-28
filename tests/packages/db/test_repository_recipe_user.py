"""Тесты для RecipeUserRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import (
    CategoryRepository,
    RecipeRepository,
    RecipeUserRepository,
    UserRepository,
)
from packages.db.schemas import (
    CategoryCreate,
    RecipeCreate,
    UserCreate,
)


class TestRecipeUserRepositoryLink:
    """Тесты для RecipeUserRepository.link_user()."""

    @pytest.mark.asyncio
    async def test_link_user_basic(self, db_session: AsyncSession) -> None:
        """Связывание пользователя с рецептом."""
        user = await UserRepository(db_session).create(UserCreate(id=12121212, username="recipe_user_user"))
        category = await CategoryRepository(db_session).create(CategoryCreate(name="Рецепты пользователя"))
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(title="Рецепт пользователя", user_id=user.id, category_id=category.id),
        )

        ru_repo = RecipeUserRepository(db_session)
        await ru_repo.link_user(recipe.id, user.id, category.id)

        assert await ru_repo.is_linked(recipe.id, user.id) is True

    @pytest.mark.asyncio
    async def test_link_user_duplicate_ignored(self, db_session: AsyncSession) -> None:
        """Дублирующаяся связь игнорируется."""
        user = await UserRepository(db_session).create(UserCreate(id=13131313, username="recipe_user_user2"))
        category = await CategoryRepository(db_session).create(CategoryCreate(name="Рецепты 2"))
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(title="Рецепт 2", user_id=user.id, category_id=category.id),
        )

        ru_repo = RecipeUserRepository(db_session)
        await ru_repo.link_user(recipe.id, user.id, category.id)
        await ru_repo.link_user(recipe.id, user.id, category.id)

        assert await ru_repo.is_linked(recipe.id, user.id) is True


class TestRecipeUserRepositoryUpsert:
    """Тесты для RecipeUserRepository.upsert_user_link()."""

    @pytest.mark.asyncio
    async def test_upsert_update_existing(self, db_session: AsyncSession) -> None:
        """Обновление существующей связи через upsert."""
        user = await UserRepository(db_session).create(UserCreate(id=15151515, username="recipe_user_user4"))
        cat_repo = CategoryRepository(db_session)
        category1 = await cat_repo.create(CategoryCreate(name="Категория 1"))
        category2 = await cat_repo.create(CategoryCreate(name="Категория 2"))
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(title="Рецепт для обновления", user_id=user.id, category_id=category1.id),
        )

        created = await RecipeUserRepository(db_session).upsert_user_link(recipe.id, user.id, category2.id)
        assert created is False


class TestRecipeUserRepositoryUnlink:
    """Тесты для RecipeUserRepository.unlink_user()."""

    @pytest.mark.asyncio
    async def test_unlink_user(self, db_session: AsyncSession) -> None:
        """Удаление связи пользователя с рецептом."""
        user = await UserRepository(db_session).create(UserCreate(id=16161616, username="recipe_user_user5"))
        category = await CategoryRepository(db_session).create(CategoryCreate(name="Рецепты 5"))
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(title="Рецепт 5", user_id=user.id, category_id=category.id),
        )

        ru_repo = RecipeUserRepository(db_session)
        await ru_repo.link_user(recipe.id, user.id, category.id)
        assert await ru_repo.is_linked(recipe.id, user.id) is True

        await ru_repo.unlink_user(recipe.id, user.id)
        await db_session.flush()

        assert await ru_repo.is_linked(recipe.id, user.id) is False


class TestRecipeUserRepositoryCheck:
    """Тесты для RecipeUserRepository.is_linked()."""

    @pytest.mark.asyncio
    async def test_is_linked_true(self, db_session: AsyncSession) -> None:
        """Проверка существующей связи."""
        user = await UserRepository(db_session).create(UserCreate(id=17171717, username="recipe_user_user6"))
        category = await CategoryRepository(db_session).create(CategoryCreate(name="Рецепты 6"))
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(title="Рецепт 6", user_id=user.id, category_id=category.id),
        )

        ru_repo = RecipeUserRepository(db_session)
        await ru_repo.link_user(recipe.id, user.id, category.id)

        assert await ru_repo.is_linked(recipe.id, user.id) is True

    @pytest.mark.asyncio
    async def test_is_linked_false(self, db_session: AsyncSession) -> None:
        """Проверка несуществующей связи."""
        user_repo = UserRepository(db_session)
        user1 = await user_repo.create(UserCreate(id=18181818, username="recipe_user_user7"))
        user2 = await user_repo.create(UserCreate(id=18181819, username="recipe_user_user7b"))
        category = await CategoryRepository(db_session).create(CategoryCreate(name="Рецепты 7"))
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(title="Рецепт 7", user_id=user1.id, category_id=category.id),
        )

        assert await RecipeUserRepository(db_session).is_linked(recipe.id, user2.id) is False


class TestRecipeUserRepositoryGetCategory:
    """Тесты для RecipeUserRepository.get_any_category_id()."""

    @pytest.mark.asyncio
    async def test_get_any_category_id(self, db_session: AsyncSession) -> None:
        """Получение любой категории рецепта."""
        user = await UserRepository(db_session).create(UserCreate(id=19191919, username="recipe_user_user8"))
        category = await CategoryRepository(db_session).create(CategoryCreate(name="Рецепты 8"))
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(title="Рецепт 8", user_id=user.id, category_id=category.id),
        )

        ru_repo = RecipeUserRepository(db_session)
        await ru_repo.link_user(recipe.id, user.id, category.id)

        assert await ru_repo.get_any_category_id(recipe.id) == category.id

    @pytest.mark.asyncio
    async def test_get_any_category_id_no_links(self, db_session: AsyncSession) -> None:
        """Получение категории для рецепта без связей возвращает None."""
        recipe = await RecipeRepository(db_session).create_basic(title="Рецепт 9", description="Без связей")

        assert await RecipeUserRepository(db_session).get_any_category_id(recipe.id) is None


class TestRecipeUserRepositoryIntegration:
    """Интеграционные тесты для RecipeUserRepository."""

    @pytest.mark.asyncio
    async def test_recipe_user_lifecycle(self, db_session: AsyncSession) -> None:
        """Полный цикл жизни связи рецепт-пользователь."""
        user = await UserRepository(db_session).create(UserCreate(id=21212121, username="recipe_user_user10"))
        category = await CategoryRepository(db_session).create(CategoryCreate(name="Рецепты 10"))
        recipe = await RecipeRepository(db_session).create_basic(title="Рецепт 10", description="Для полного цикла")

        ru_repo = RecipeUserRepository(db_session)

        assert await ru_repo.is_linked(recipe.id, user.id) is False

        await ru_repo.link_user(recipe.id, user.id, category.id)
        assert await ru_repo.is_linked(recipe.id, user.id) is True
        assert await ru_repo.get_any_category_id(recipe.id) == category.id

        await ru_repo.unlink_user(recipe.id, user.id)
        await db_session.flush()

        assert await ru_repo.is_linked(recipe.id, user.id) is False
        assert await ru_repo.get_any_category_id(recipe.id) is None
