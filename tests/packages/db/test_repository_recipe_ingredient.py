"""Тесты для RecipeIngredientRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import (
    CategoryRepository,
    IngredientRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    UserRepository,
)
from packages.db.schemas import (
    CategoryCreate,
    RecipeCreate,
    UserCreate,
)


class TestRecipeIngredientRepositoryCreate:
    """Тесты для RecipeIngredientRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_recipe_ingredient(self, db_session: AsyncSession) -> None:
        """Создание связи рецепт-ингредиент."""
        # Подготовка данных
        user = await UserRepository(db_session).create(
            UserCreate(id=4444444, username="recipe_ing_user"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями"),
        )
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(
                title="Рецепт с ингредиентом",
                user_id=user.id,
                category_id=category.id,
            ),
        )
        ingredient = await IngredientRepository(db_session).create("Помидоры")

        # Создаем связь
        recipe_ingredient = await RecipeIngredientRepository(db_session).create(recipe.id, ingredient.id)

        assert recipe_ingredient.id is not None
        assert recipe_ingredient.recipe_id == recipe.id
        assert recipe_ingredient.ingredient_id == ingredient.id

    @pytest.mark.asyncio
    async def test_create_duplicate_raises_error(self, db_session: AsyncSession) -> None:
        """Создание дублирующейся связи вызывает ValueError."""
        user = await UserRepository(db_session).create(
            UserCreate(id=5555555, username="recipe_ing_user2"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями 2"),
        )
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(
                title="Рецепт 2",
                user_id=user.id,
                category_id=category.id,
            ),
        )
        ingredient = await IngredientRepository(db_session).create("Огурец")

        ri_repo = RecipeIngredientRepository(db_session)
        # Создаем первую связь
        await ri_repo.create(recipe.id, ingredient.id)

        # Пытаемся создать дублирующуюся
        with pytest.raises(ValueError, match="RecipeIngredient already exists"):
            await ri_repo.create(recipe.id, ingredient.id)


class TestRecipeIngredientRepositoryBulk:
    """Тесты для RecipeIngredientRepository.bulk_link()."""

    @pytest.mark.asyncio
    async def test_bulk_link_ingredients(self, db_session: AsyncSession) -> None:
        """Массовое связывание ингредиентов с рецептом."""
        user = await UserRepository(db_session).create(
            UserCreate(id=6666666, username="recipe_ing_user3"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями 3"),
        )
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(
                title="Рецепт с многими ингредиентами",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Создаем ингредиенты
        ing_repo = IngredientRepository(db_session)
        ing1 = await ing_repo.create("Маслo")
        ing2 = await ing_repo.create("Соль")
        ing3 = await ing_repo.create("Перец")

        # Массовое связывание (не должно вызывать ошибок)
        await RecipeIngredientRepository(db_session).bulk_link(recipe.id, [ing1.id, ing2.id, ing3.id])

    @pytest.mark.asyncio
    async def test_bulk_link_empty_list(self, db_session: AsyncSession) -> None:
        """Массовое связывание с пустым списком."""
        user = await UserRepository(db_session).create(
            UserCreate(id=7777777, username="recipe_ing_user4"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями 4"),
        )
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(
                title="Рецепт без ингредиентов",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Должно работать без ошибок
        await RecipeIngredientRepository(db_session).bulk_link(recipe.id, [])

    @pytest.mark.asyncio
    async def test_bulk_link_ignores_duplicates(self, db_session: AsyncSession) -> None:
        """Дубликаты в bulk_link игнорируются."""
        user = await UserRepository(db_session).create(
            UserCreate(id=8888888, username="recipe_ing_user5"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями 5"),
        )
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(
                title="Рецепт с дубликатами",
                user_id=user.id,
                category_id=category.id,
            ),
        )
        ingredient = await IngredientRepository(db_session).create("Уксус")

        ri_repo = RecipeIngredientRepository(db_session)
        # Передаем один ID несколько раз
        await ri_repo.bulk_link(recipe.id, [ingredient.id, ingredient.id, ingredient.id])

        # Пытаемся создать еще одну - должно быть ошибка
        with pytest.raises(ValueError):
            await ri_repo.create(recipe.id, ingredient.id)

    @pytest.mark.asyncio
    async def test_bulk_link_with_none_values(self, db_session: AsyncSession) -> None:
        """bulk_link игнорирует None и нулевые значения."""
        user = await UserRepository(db_session).create(
            UserCreate(id=9999999, username="recipe_ing_user6"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями 6"),
        )
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(
                title="Рецепт с None",
                user_id=user.id,
                category_id=category.id,
            ),
        )
        ingredient = await IngredientRepository(db_session).create("Сахар")

        ri_repo = RecipeIngredientRepository(db_session)
        # Передаем None значения вместе с валидными
        await ri_repo.bulk_link(recipe.id, [ingredient.id, None, 0])  # type: ignore[list-item]

        # Должна быть создана связь только для валидного ID
        with pytest.raises(ValueError):
            await ri_repo.create(recipe.id, ingredient.id)


class TestRecipeIngredientRepositoryIntegration:
    """Интеграционные тесты для RecipeIngredientRepository."""

    @pytest.mark.asyncio
    async def test_recipe_with_multiple_ingredients(self, db_session: AsyncSession) -> None:
        """Рецепт может быть связан с несколькими ингредиентами."""
        user = await UserRepository(db_session).create(
            UserCreate(id=10101010, username="recipe_ing_user7"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями 7"),
        )
        recipe = await RecipeRepository(db_session).create(
            RecipeCreate(
                title="Сложный рецепт",
                user_id=user.id,
                category_id=category.id,
            ),
        )

        # Создаем ингредиенты
        ing_repo = IngredientRepository(db_session)
        ri_repo = RecipeIngredientRepository(db_session)
        ingredients = []
        for name in ["Молоко", "Яйцо", "Мука", "Сахар"]:
            ing = await ing_repo.create(name)
            ingredients.append(ing.id)

        # Связываем все ингредиенты с рецептом
        await ri_repo.bulk_link(recipe.id, ingredients)

        # Проверяем что связи созданы, пытаясь создать дублирующуюся
        for ing_id in ingredients:
            with pytest.raises(ValueError):
                await ri_repo.create(recipe.id, ing_id)

    @pytest.mark.asyncio
    async def test_one_ingredient_multiple_recipes(self, db_session: AsyncSession) -> None:
        """Один ингредиент может быть связан с несколькими рецептами."""
        user = await UserRepository(db_session).create(
            UserCreate(id=11111111, username="recipe_ing_user8"),
        )
        category = await CategoryRepository(db_session).create(
            CategoryCreate(name="Со связями 8"),
        )

        # Создаем ингредиент
        ingredient = await IngredientRepository(db_session).create("Масло")

        # Создаем несколько рецептов
        recipe_repo = RecipeRepository(db_session)
        ri_repo = RecipeIngredientRepository(db_session)
        recipes = []
        for i in range(3):
            recipe = await recipe_repo.create(
                RecipeCreate(
                    title=f"Рецепт {i}",
                    user_id=user.id,
                    category_id=category.id,
                ),
            )
            recipes.append(recipe.id)

        # Связываем ингредиент со всеми рецептами
        created_count = 0
        for recipe_id in recipes:
            recipe_ingredient = await ri_repo.create(recipe_id, ingredient.id)
            if recipe_ingredient:
                created_count += 1

        assert created_count == 3
