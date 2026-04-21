"""Тесты для IngredientRepository."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import IngredientRepository


class TestIngredientRepositoryCreate:
    """Тесты для IngredientRepository.create()."""

    @pytest.mark.asyncio
    async def test_create_ingredient_basic(self, db_session: AsyncSession) -> None:
        """Создание базового ингредиента."""
        ingredient = await IngredientRepository.create(db_session, "Помидоры")

        assert ingredient.id is not None
        assert ingredient.name == "Помидоры"

    @pytest.mark.asyncio
    async def test_create_multiple_ingredients(self, db_session: AsyncSession) -> None:
        """Создание нескольких ингредиентов."""
        ing1 = await IngredientRepository.create(db_session, "Масло")
        ing2 = await IngredientRepository.create(db_session, "Соль")
        ing3 = await IngredientRepository.create(db_session, "Перец")

        assert ing1.id is not None
        assert ing2.id is not None
        assert ing3.id is not None
        assert ing1.id != ing2.id != ing3.id

    @pytest.mark.asyncio
    async def test_create_existing_ingredient_returns_same(self, db_session: AsyncSession) -> None:
        """Создание существующего ингредиента возвращает тот же объект."""
        ing1 = await IngredientRepository.create(db_session, "Чеснок")
        ing2 = await IngredientRepository.create(db_session, "Чеснок")

        assert ing1.id == ing2.id
        assert ing1.name == ing2.name

    @pytest.mark.asyncio
    async def test_create_ingredient_with_whitespace(self, db_session: AsyncSession) -> None:
        """Создание ингредиента с пробельными символами."""
        ingredient = await IngredientRepository.create(db_session, "  Зелень петрушки  ")

        assert ingredient.name == "  Зелень петрушки  "

    @pytest.mark.asyncio
    async def test_create_ingredient_case_sensitive(self, db_session: AsyncSession) -> None:
        """Создание ингредиентов с разным регистром создает разные объекты."""
        ing1 = await IngredientRepository.create(db_session, "Морковь")
        ing2 = await IngredientRepository.create(db_session, "морковь")

        assert ing1.id != ing2.id


class TestIngredientRepositoryGet:
    """Тесты для методов получения ингредиентов."""

    @pytest.mark.asyncio
    async def test_get_by_name(self, db_session: AsyncSession) -> None:
        """Получение ингредиента по названию."""
        created = await IngredientRepository.create(db_session, "Лимон")

        retrieved = await IngredientRepository.get_by_name(db_session, "Лимон")

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "Лимон"

    @pytest.mark.asyncio
    async def test_get_by_nonexistent_name(self, db_session: AsyncSession) -> None:
        """Получение несуществующего ингредиента возвращает None."""
        result = await IngredientRepository.get_by_name(db_session, "Несуществующий ингредиент")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_name_case_sensitive(self, db_session: AsyncSession) -> None:
        """Поиск по названию чувствителен к регистру."""
        await IngredientRepository.create(db_session, "Огурец")

        result = await IngredientRepository.get_by_name(db_session, "огурец")

        assert result is None


class TestIngredientRepositoryBulk:
    """Тесты для IngredientRepository.bulk_get_or_create()."""

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_new(self, db_session: AsyncSession) -> None:
        """Массовое создание новых ингредиентов."""
        names = ["Картофель", "Капуста", "Морковь"]

        result = await IngredientRepository.bulk_get_or_create(db_session, names)

        assert len(result) == 3
        assert "Картофель" in result
        assert "Капуста" in result
        assert "Морковь" in result
        assert all(isinstance(v, int) for v in result.values())

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_existing(self, db_session: AsyncSession) -> None:
        """Массовое получение существующих ингредиентов."""
        # Создаем ингредиенты
        ing1 = await IngredientRepository.create(db_session, "Бук")
        ing2 = await IngredientRepository.create(db_session, "Укроп")

        # Получаем их же через bulk
        result = await IngredientRepository.bulk_get_or_create(db_session, ["Бук", "Укроп"])

        assert result["Бук"] == ing1.id
        assert result["Укроп"] == ing2.id

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_mixed(self, db_session: AsyncSession) -> None:
        """Смешанное получение существующих и создание новых."""
        # Создаем один ингредиент
        existing = await IngredientRepository.create(db_session, "Луковица")

        # Запрашиваем существующий и новый
        result = await IngredientRepository.bulk_get_or_create(db_session, ["Луковица", "Редис"])

        assert result["Луковица"] == existing.id
        assert "Редис" in result
        assert isinstance(result["Редис"], int)

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_empty_list(self, db_session: AsyncSession) -> None:
        """Массовое создание с пустым списком возвращает пустой словарь."""
        result = await IngredientRepository.bulk_get_or_create(db_session, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_with_empty_strings(self, db_session: AsyncSession) -> None:
        """Пустые строки в списке игнорируются."""
        result = await IngredientRepository.bulk_get_or_create(
            db_session, ["Кабачок", "", "Баклажан", None]  # type: ignore[list-item]
        )

        assert len(result) == 2
        assert "Кабачок" in result
        assert "Баклажан" in result

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_removes_duplicates(self, db_session: AsyncSession) -> None:
        """Дубликаты в списке обработаны правильно."""
        result = await IngredientRepository.bulk_get_or_create(db_session, ["Лук", "Лук", "Чеснок"])

        assert len(result) == 2
        assert "Лук" in result
        assert "Чеснок" in result

    @pytest.mark.asyncio
    async def test_bulk_get_or_create_with_whitespace(self, db_session: AsyncSession) -> None:
        """Пробелы в названиях удаляются."""
        result = await IngredientRepository.bulk_get_or_create(db_session, ["  Йогурт  ", "Сметана"])

        assert len(result) == 2
        # Пробелы удаляются функцией
        assert "Йогурт" in result
        assert "Сметана" in result


class TestIngredientRepositoryIntegration:
    """Интеграционные тесты для IngredientRepository."""

    @pytest.mark.asyncio
    async def test_create_get_consistency(self, db_session: AsyncSession) -> None:
        """Консистентность между create и get."""
        created = await IngredientRepository.create(db_session, "Сливочное масло")
        retrieved = await IngredientRepository.get_by_name(db_session, "Сливочное масло")

        assert retrieved is not None
        assert created.id == retrieved.id
        assert created.name == retrieved.name

    @pytest.mark.asyncio
    async def test_bulk_create_consistency(self, db_session: AsyncSession) -> None:
        """Консистентность bulk_get_or_create с get_by_name."""
        names = ["Помидор", "Огурец", "Перец"]
        bulk_result = await IngredientRepository.bulk_get_or_create(db_session, names)

        for name in names:
            retrieved = await IngredientRepository.get_by_name(db_session, name)
            assert retrieved is not None
            assert retrieved.id == bulk_result[name]

    @pytest.mark.asyncio
    async def test_ingredient_uniqueness_by_name(self, db_session: AsyncSession) -> None:
        """Каждое уникальное название имеет уникальный ID."""
        names = ["Яблоко", "Груша", "Апельсин", "Банан"]
        ids = []

        for name in names:
            ing = await IngredientRepository.create(db_session, name)
            ids.append(ing.id)

        # Все ID должны быть уникальными
        assert len(ids) == len(set(ids))
