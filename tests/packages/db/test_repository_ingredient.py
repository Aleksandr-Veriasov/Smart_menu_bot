"""Тесты для IngredientRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import IngredientRepository


class TestIngredientRepositoryCreate:
    """Тесты для IngredientRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_ingredient_basic(self, db_session: AsyncSession) -> None:
        """Создание базового ингредиента."""
        ingredient = await IngredientRepository(db_session).create("Помидоры")

        assert ingredient.id is not None
        assert ingredient.name == "Помидоры"

    @pytest.mark.asyncio
    async def test_create_multiple_ingredients(self, db_session: AsyncSession) -> None:
        """Создание нескольких ингредиентов."""
        repo = IngredientRepository(db_session)
        ing1 = await repo.create("Масло")
        ing2 = await repo.create("Соль")
        ing3 = await repo.create("Перец")

        assert ing1.id is not None
        assert ing2.id is not None
        assert ing3.id is not None
        assert ing1.id != ing2.id != ing3.id

    @pytest.mark.asyncio
    async def test_create_existing_ingredient_returns_same(self, db_session: AsyncSession) -> None:
        """get_or_create возвращает существующий ингредиент без дублирования."""
        repo = IngredientRepository(db_session)
        ing1 = await repo.get_or_create("Чеснок")
        ing2 = await repo.get_or_create("Чеснок")

        assert ing1.id == ing2.id
        assert ing1.name == ing2.name

    @pytest.mark.asyncio
    async def test_create_ingredient_with_whitespace(self, db_session: AsyncSession) -> None:
        """Создание ингредиента с пробельными символами."""
        ingredient = await IngredientRepository(db_session).create("  Зелень петрушки  ")

        assert ingredient.name == "  Зелень петрушки  "

    @pytest.mark.asyncio
    async def test_create_ingredient_case_sensitive(self, db_session: AsyncSession) -> None:
        """Создание ингредиентов с разным регистром создает разные объекты."""
        repo = IngredientRepository(db_session)
        ing1 = await repo.create("Морковь")
        ing2 = await repo.create("морковь")

        assert ing1.id != ing2.id


class TestIngredientRepositoryGet:
    """Тесты для методов получения ингредиентов."""

    @pytest.mark.asyncio
    async def test_get_by_name(self, db_session: AsyncSession) -> None:
        """Получение ингредиента по названию."""
        repo = IngredientRepository(db_session)
        created = await repo.create("Лимон")

        retrieved = await repo.get_by_name("Лимон")

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "Лимон"

    @pytest.mark.asyncio
    async def test_get_by_nonexistent_name(self, db_session: AsyncSession) -> None:
        """Получение несуществующего ингредиента возвращает None."""
        result = await IngredientRepository(db_session).get_by_name("Несуществующий ингредиент")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_name_case_sensitive(self, db_session: AsyncSession) -> None:
        """Поиск по названию чувствителен к регистру."""
        repo = IngredientRepository(db_session)
        await repo.create("Огурец")

        result = await repo.get_by_name("огурец")

        assert result is None


class TestIngredientRepositoryBulk:
    """Тесты для IngredientRepository.bulk_get_or_create()."""

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_new(self, db_session: AsyncSession) -> None:
        """Массовое создание новых ингредиентов."""
        names = ["Картофель", "Капуста", "Морковь"]

        result = await IngredientRepository(db_session).bulk_get_or_create(names)

        assert len(result) == 3
        assert "Картофель" in result
        assert "Капуста" in result
        assert "Морковь" in result
        assert all(isinstance(v, int) for v in result.values())

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_existing(self, db_session: AsyncSession) -> None:
        """Массовое получение существующих ингредиентов."""
        repo = IngredientRepository(db_session)
        # Создаем ингредиенты
        ing1 = await repo.create("Бук")
        ing2 = await repo.create("Укроп")

        # Получаем их же через bulk
        result = await repo.bulk_get_or_create(["Бук", "Укроп"])

        assert result["Бук"] == ing1.id
        assert result["Укроп"] == ing2.id

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_mixed(self, db_session: AsyncSession) -> None:
        """Смешанное получение существующих и создание новых."""
        repo = IngredientRepository(db_session)
        # Создаем один ингредиент
        existing = await repo.create("Луковица")

        # Запрашиваем существующий и новый
        result = await repo.bulk_get_or_create(["Луковица", "Редис"])

        assert result["Луковица"] == existing.id
        assert "Редис" in result
        assert isinstance(result["Редис"], int)

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_empty_list(self, db_session: AsyncSession) -> None:
        """Массовое создание с пустым списком возвращает пустой словарь."""
        result = await IngredientRepository(db_session).bulk_get_or_create([])

        assert result == {}

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_with_empty_strings(self, db_session: AsyncSession) -> None:
        """Пустые строки в списке игнорируются."""
        result = await IngredientRepository(db_session).bulk_get_or_create(
            ["Кабачок", "", "Баклажан", None]  # type: ignore[list-item]
        )

        assert len(result) == 2
        assert "Кабачок" in result
        assert "Баклажан" in result

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_removes_duplicates(self, db_session: AsyncSession) -> None:
        """Дубликаты в списке обработаны правильно."""
        result = await IngredientRepository(db_session).bulk_get_or_create(["Лук", "Лук", "Чеснок"])

        assert len(result) == 2
        assert "Лук" in result
        assert "Чеснок" in result

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_with_whitespace(self, db_session: AsyncSession) -> None:
        """Пробелы в названиях удаляются."""
        result = await IngredientRepository(db_session).bulk_get_or_create(["  Йогурт  ", "Сметана"])

        assert len(result) == 2
        # Пробелы удаляются функцией
        assert "Йогурт" in result
        assert "Сметана" in result


class TestIngredientRepositoryIntegration:
    """Интеграционные тесты для IngredientRepository."""

    @pytest.mark.asyncio
    async def test_create_get_consistency(self, db_session: AsyncSession) -> None:
        """Консистентность между create и get."""
        repo = IngredientRepository(db_session)
        created = await repo.create("Сливочное масло")
        retrieved = await repo.get_by_name("Сливочное масло")

        assert retrieved is not None
        assert created.id == retrieved.id
        assert created.name == retrieved.name

    @pytest.mark.asyncio
    async def test_bulk_create_consistency(self, db_session: AsyncSession) -> None:
        """Консистентность bulk_get_or_create с get_by_name."""
        repo = IngredientRepository(db_session)
        names = ["Помидор", "Огурец", "Перец"]
        bulk_result = await repo.bulk_get_or_create(names)

        for name in names:
            retrieved = await repo.get_by_name(name)
            assert retrieved is not None
            assert retrieved.id == bulk_result[name]

    @pytest.mark.asyncio
    async def test_ingredient_uniqueness_by_name(self, db_session: AsyncSession) -> None:
        """Каждое уникальное название имеет уникальный ID."""
        repo = IngredientRepository(db_session)
        names = ["Яблоко", "Груша", "Апельсин", "Банан"]
        ids = []

        for name in names:
            ing = await repo.create(name)
            ids.append(ing.id)

        # Все ID должны быть уникальными
        assert len(ids) == len(set(ids))
