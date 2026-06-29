"""Тесты парсеров LLM-ответов: parse_structured_answer и parse_llm_answer."""

import json
from decimal import Decimal

from packages.recipes_core.deepseek_parsers import (
    IngredientItem,
    parse_llm_answer,
    parse_structured_answer,
)

# ── parse_structured_answer ────────────────────────────────────────────────────


class TestParseStructuredAnswer:

    def _make(self, **kwargs) -> str:
        base = {
            "title": "Блины",
            "instructions": "1. Смешать\n2. Жарить",
            "ingredients": [],
        }
        base.update(kwargs)
        return json.dumps(base, ensure_ascii=False)

    def test_valid_full(self):
        raw = self._make(
            ingredients=[
                {"name": "мука", "quantity": 200, "unit": "г"},
                {"name": "молоко", "quantity": 0.5, "unit": "л"},
            ]
        )
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.title == "Блины"
        assert result.instructions_text == "1. Смешать\n2. Жарить"
        assert len(result.ingredients) == 2
        assert result.ingredients[0] == IngredientItem(name="мука", quantity=Decimal("200"), unit="г")
        assert result.ingredients[1] == IngredientItem(name="молоко", quantity=Decimal("0.5"), unit="л")

    def test_partial_no_quantity(self):
        """Ингредиент без quantity — quantity=None, остальное сохраняется."""
        raw = self._make(
            ingredients=[
                {"name": "соль", "quantity": None, "unit": "по вкусу"},
            ]
        )
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.ingredients[0].quantity is None
        assert result.ingredients[0].unit == "по вкусу"

    def test_partial_no_unit(self):
        """Ингредиент без unit — unit=None."""
        raw = self._make(
            ingredients=[
                {"name": "яйца", "quantity": 3, "unit": None},
            ]
        )
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.ingredients[0].quantity == Decimal("3")
        assert result.ingredients[0].unit is None

    def test_partial_name_only(self):
        """Ингредиент только с именем — qty и unit = None."""
        raw = self._make(ingredients=[{"name": "перец"}])
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.ingredients[0].name == "перец"
        assert result.ingredients[0].quantity is None
        assert result.ingredients[0].unit is None

    def test_unit_alias_normalized(self):
        """Алиас единицы нормализуется через normalize_unit."""
        raw = self._make(
            ingredients=[
                {"name": "мука", "quantity": 200, "unit": "грамм"},
            ]
        )
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.ingredients[0].unit == "г"

    def test_empty_ingredients_list(self):
        """Пустой список ингредиентов — валидный ответ."""
        raw = self._make(ingredients=[])
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.ingredients == []

    def test_invalid_quantity_string_ignored(self):
        """Нечисловое quantity → None, ингредиент не теряется."""
        raw = self._make(
            ingredients=[
                {"name": "мука", "quantity": "много", "unit": "г"},
            ]
        )
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.ingredients[0].quantity is None

    def test_ingredient_without_name_skipped(self):
        """Ингредиент без name пропускается."""
        raw = self._make(
            ingredients=[
                {"quantity": 100, "unit": "г"},
                {"name": "соль"},
            ]
        )
        result = parse_structured_answer(raw)
        assert result is not None
        assert len(result.ingredients) == 1
        assert result.ingredients[0].name == "соль"

    def test_garbage_returns_none(self):
        """Произвольная строка → None (вызывающий код делает фолбэк)."""
        assert parse_structured_answer("это не json") is None
        assert parse_structured_answer("") is None
        assert parse_structured_answer("null") is None

    def test_json_array_at_root_returns_none(self):
        """JSON-массив вместо объекта → None."""
        assert parse_structured_answer("[1, 2, 3]") is None

    def test_ingredients_list_property(self):
        """ingredients_list возвращает имена из structured ingredients."""
        raw = self._make(
            ingredients=[
                {"name": "мука", "quantity": 200, "unit": "г"},
                {"name": "соль"},
            ]
        )
        result = parse_structured_answer(raw)
        assert result.ingredients_list == ["мука", "соль"]

    def test_raw_preserved(self):
        """Сырой ответ сохраняется в .raw."""
        raw = self._make()
        result = parse_structured_answer(raw)
        assert result.raw == raw


# ── parse_llm_answer (легаси) ──────────────────────────────────────────────────


class TestParseLlmAnswer:

    def test_valid_full(self):
        content = "Название рецепта: Борщ\n" "Рецепт:\n1. Варить\n2. Подавать\n" "Ингредиенты:\n- Свёкла\n- Капуста\n"
        result = parse_llm_answer(content)
        assert result.title == "Борщ"
        assert "Варить" in result.instructions_text
        assert result.ingredients_list == ["Свёкла", "Капуста"]

    def test_empty_content(self):
        result = parse_llm_answer("")
        assert result.title == "Не указано"
        assert result.instructions_text == "Не указан"
        assert result.ingredients_list == []

    def test_garbage_content(self):
        result = parse_llm_answer("какой-то мусор без формата")
        assert result.title == "Не указано"
        assert result.ingredients_list == []

    def test_ingredients_list_falls_back_to_text(self):
        """ingredients_list из текстового формата — когда structured пуст."""
        result = parse_llm_answer("Ингредиенты:\n- Морковь\n- Лук\n")
        assert result.ingredients == []
        assert result.ingredients_list == ["Морковь", "Лук"]


# ── фолбэк-логика: structured → legacy ─────────────────────────────────────────


class TestFallbackLogic:

    def test_structured_none_signals_fallback(self):
        """parse_structured_answer возвращает None → нужен фолбэк на parse_llm_answer."""
        raw = "Название рецепта: Суп\nИнгредиенты:\n- Вода\n"
        structured = parse_structured_answer(raw)
        assert structured is None

        fallback = parse_llm_answer(raw)
        assert fallback.title == "Суп"
        assert "Вода" in fallback.ingredients_list

    def test_structured_success_no_fallback_needed(self):
        """Валидный JSON → structured result, fallback не нужен."""
        raw = json.dumps({"title": "Суп", "instructions": "1. Варить", "ingredients": []})
        result = parse_structured_answer(raw)
        assert result is not None
        assert result.title == "Суп"
