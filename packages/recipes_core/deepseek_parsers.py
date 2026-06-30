"""Pydantic-модели и парсеры ответов LLM для экстракции рецептов.

parse_structured_answer() — новый путь: JSON-ответ → RecipeExtraction с заполненными ingredients.
parse_llm_answer()        — легаси путь: текстовый формат → RecipeExtraction (ingredients_text).
"""

import json
import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from packages.recipes_core.units import normalize_unit
from packages.utils import normalize_quantity


class IngredientItem(BaseModel):
    name: str
    quantity: Decimal | None = None
    unit: str | None = None


class RecipeExtraction(BaseModel):
    title: str = Field(default="Не указано")
    instructions_text: str = Field(default="Не указан")
    ingredients_text: str = Field(default="Не указаны")  # легаси, для обратной совместимости
    ingredients: list[IngredientItem] = Field(default_factory=list)
    raw: str = ""

    @property
    def ingredients_list(self) -> list[str]:
        if self.ingredients:
            return [item.name for item in self.ingredients]
        return [
            re.sub(r"^[-*]\s*", "", line).strip()
            for line in self.ingredients_text.splitlines()
            if line.strip() and re.match(r"^[-*]\s*", line.strip())
        ]


def _parse_quantity(value: object) -> Decimal | None:
    """Конвертирует значение из JSON в Decimal; возвращает None при невалидном вводе."""
    if value is None:
        return None
    try:
        return normalize_quantity(Decimal(str(value)))
    except InvalidOperation:
        return None


def parse_structured_answer(content: str) -> RecipeExtraction:
    """Парсит JSON-ответ нового формата (SYSTEM_PROMPT_STRUCTURED).

    Возвращает None если content не является валидным JSON или не содержит ожидаемой структуры —
    вызывающий код должен сделать фолбэк на parse_llm_answer().
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None  # type: ignore[return-value]

    if not isinstance(data, dict):
        return None  # type: ignore[return-value]

    raw_ingredients = data.get("ingredients") or []
    ingredients = []
    for item in raw_ingredients:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        ingredients.append(
            IngredientItem(
                name=str(item["name"]).strip(),
                quantity=_parse_quantity(item.get("quantity")),
                unit=normalize_unit(item.get("unit")),
            )
        )

    return RecipeExtraction(
        title=str(data.get("title") or "Не указано").strip(),
        instructions_text=str(data.get("instructions") or "Не указан").strip(),
        ingredients=ingredients,
        raw=content,
    )


def parse_llm_answer(content: str) -> RecipeExtraction:
    """
    Парсим легаси текстовый формат:
    Название рецепта: ...
    Рецепт:
    1. ...
    Ингредиенты:
    - ...
    """
    lines = [line.strip() for line in (content or "").splitlines()]
    title = ""
    rec = []
    ing = []

    mode = None  # 'recipe' | 'ingredients' | None
    for line in lines:
        if not line:
            continue
        if line.startswith("Название рецепта:"):
            title = line.split(":", 1)[1].strip()
            mode = None
            continue
        if line.startswith("Рецепт:"):
            mode = "recipe"
            tail = line.replace("Рецепт:", "", 1).strip()
            if tail:
                rec.append(tail)
            continue
        if line.startswith("Ингредиенты:"):
            mode = "ingredients"
            tail = line.replace("Ингредиенты:", "", 1).strip()
            if tail:
                ing.append(tail)
            continue

        if mode == "recipe":
            rec.append(line)
        elif mode == "ingredients":
            if not re.match(r"^[-*]\s+", line):
                line = f"- {line}"
            ing.append(line)

    return RecipeExtraction(
        title=title or "Не указано",
        instructions_text="\n".join(rec) or "Не указан",
        ingredients_text="\n".join(ing) or "Не указаны",
        raw=content or "",
    )
