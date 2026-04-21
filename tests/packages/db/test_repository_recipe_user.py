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
        user = await UserRepository.create(
            db_session,
            UserCreate(id=12121212, username="recipe_user_user"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты пользователя"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт пользователя",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Связываем (не должно быть ошибок)
        await RecipeUserRepository.link_user(db_session, recipe.id, user.id, category.id)

        # Проверяем что связь создана
        is_linked = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked is True

    @pytest.mark.asyncio
    async def test_link_user_duplicate_ignored(self, db_session: AsyncSession) -> None:
        """Дублирующаяся связь игнорируется."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=13131313, username="recipe_user_user2"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты 2"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 2",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Связываем дважды (не должно быть ошибок)
        await RecipeUserRepository.link_user(db_session, recipe.id, user.id, category.id)
        await RecipeUserRepository.link_user(db_session, recipe.id, user.id, category.id)

        # Проверяем что связь существует
        is_linked = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked is True


class TestRecipeUserRepositoryUpsert:
    """Тесты для RecipeUserRepository.upsert_user_link()."""

    @pytest.mark.asyncio
    async def test_upsert_update_existing(self, db_session: AsyncSession) -> None:
        """Обновление существующей связи через upsert."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=15151515, username="recipe_user_user4"),
        )
        category1 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Категория 1"),
        )
        category2 = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Категория 2"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт для обновления",
                user_id=user.id,
                category_id=category1.id,
            ),
        )

        # Уже есть связь из create() - обновляем ее
        created = await RecipeUserRepository.upsert_user_link(db_session, recipe.id, user.id, category2.id)
        assert created is False


class TestRecipeUserRepositoryUnlink:
    """Тесты для RecipeUserRepository.unlink_user()."""

    @pytest.mark.asyncio
    async def test_unlink_user(self, db_session: AsyncSession) -> None:
        """Удаление связи пользователя с рецептом."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=16161616, username="recipe_user_user5"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты 5"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 5",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Связываем
        await RecipeUserRepository.link_user(db_session, recipe.id, user.id, category.id)

        # Проверяем что связь есть
        is_linked_before = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked_before is True

        # Удаляем связь
        await RecipeUserRepository.unlink_user(db_session, recipe.id, user.id)
        await db_session.flush()

        # Проверяем что связь удалена
        is_linked_after = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked_after is False


class TestRecipeUserRepositoryCheck:
    """Тесты для RecipeUserRepository.is_linked()."""

    @pytest.mark.asyncio
    async def test_is_linked_true(self, db_session: AsyncSession) -> None:
        """Проверка существующей связи."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=17171717, username="recipe_user_user6"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты 6"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 6",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Связываем
        await RecipeUserRepository.link_user(db_session, recipe.id, user.id, category.id)

        # Проверяем
        is_linked = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked is True

    @pytest.mark.asyncio
    async def test_is_linked_false(self, db_session: AsyncSession) -> None:
        """Проверка несуществующей связи."""
        user1 = await UserRepository.create(
            db_session,
            UserCreate(id=18181818, username="recipe_user_user7"),
        )
        user2 = await UserRepository.create(
            db_session,
            UserCreate(id=18181819, username="recipe_user_user7b"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты 7"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 7",
                user_id=user1.id,
                category_id=category.id,
            ),
        )

        # Проверяем связь с другим пользователем
        is_linked = await RecipeUserRepository.is_linked(db_session, recipe.id, user2.id)
        assert is_linked is False


class TestRecipeUserRepositoryGetCategory:
    """Тесты для RecipeUserRepository.get_any_category_id()."""

    @pytest.mark.asyncio
    async def test_get_any_category_id(self, db_session: AsyncSession) -> None:
        """Получение любой категории рецепта."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=19191919, username="recipe_user_user8"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты 8"),
        )
        recipe = await RecipeRepository.create(
            db_session,
            RecipeCreate(
                title="Рецепт 8",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Связываем
        await RecipeUserRepository.link_user(db_session, recipe.id, user.id, category.id)

        # Получаем категорию
        cat_id = await RecipeUserRepository.get_any_category_id(db_session, recipe.id)

        assert cat_id == category.id

    @pytest.mark.asyncio
    async def test_get_any_category_id_no_links(self, db_session: AsyncSession) -> None:
        """Получение категории для рецепта без связей возвращает None."""
        # Создаем рецепт БЕЗ user_id и category_id (чтобы не создавать связь)
        recipe = await RecipeRepository.create_basic(
            db_session,
            title="Рецепт 9",
            description="Без связей",
        )

        # Проверяем что нет связей
        cat_id = await RecipeUserRepository.get_any_category_id(db_session, recipe.id)

        assert cat_id is None


class TestRecipeUserRepositoryIntegration:
    """Интеграционные тесты для RecipeUserRepository."""

    @pytest.mark.asyncio
    async def test_recipe_user_lifecycle(self, db_session: AsyncSession) -> None:
        """Полный цикл жизни связи рецепт-пользователь."""
        user = await UserRepository.create(
            db_session,
            UserCreate(id=21212121, username="recipe_user_user10"),
        )
        category = await CategoryRepository.create(
            db_session,
            CategoryCreate(name="Рецепты 10"),
        )
        # Создаем рецепт БЕЗ автоматического связывания
        recipe = await RecipeRepository.create_basic(
            db_session,
            title="Рецепт 10",
            description="Для полного цикла",
        )

        # 1. Проверяем что связи нет
        is_linked = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked is False

        # 2. Создаем связь
        await RecipeUserRepository.link_user(db_session, recipe.id, user.id, category.id)

        # 3. Проверяем что связь есть
        is_linked = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked is True

        # 4. Получаем категорию
        cat_id = await RecipeUserRepository.get_any_category_id(db_session, recipe.id)
        assert cat_id == category.id

        # 5. Удаляем связь
        await RecipeUserRepository.unlink_user(db_session, recipe.id, user.id)
        await db_session.flush()

        # 6. Проверяем что связи нет
        is_linked = await RecipeUserRepository.is_linked(db_session, recipe.id, user.id)
        assert is_linked is False

        # 7. Категория не должна быть доступна
        cat_id = await RecipeUserRepository.get_any_category_id(db_session, recipe.id)
        assert cat_id is None
