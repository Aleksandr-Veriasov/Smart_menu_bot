"""Легаси-парсер ингредиентов из текстового формата LLM.

Используется в write-path до перехода на структурированный JSON-ответ (SYSTEM_PROMPT_STRUCTURED).
"""

import logging

logger = logging.getLogger(__name__)


def to_ingredient_name(x: object) -> str:
    """Извлекает строковое имя ингредиента из dict или строки."""
    if isinstance(x, dict):
        return (x.get("name") or "").strip()
    return str(x or "").strip()


def parse_ingredients(text: str) -> list:
    """Разбирает текст с маркированным списком ингредиентов (- item) в список строк."""
    logger.debug("Начинаем парсинг ингредиентов...")
    lines: list = text.strip().split("\n")
    ingredients: list = []

    for line_number, line in enumerate(lines, 1):
        logger.debug(f"Обрабатываем строку {line_number}: {line}")
        stripped_line: str = line.strip()
        if stripped_line.startswith("- "):
            ingredient_name: str = stripped_line[2:].strip()
            if ingredient_name:
                ingredients.append(ingredient_name)

    logger.debug(f"Парсинг завершен. Найдено ингредиентов: {len(ingredients)}")
    return ingredients
