import logging

logger = logging.getLogger(__name__)


def parse_ingredients(text: str) -> list:
    """
    Разбирает строку с ингредиентами и возвращает список ингредиентов.
    """
    logger.debug("Начинаем парсинг ингредиентов...")
    # Убираем лишние пробелы и символы
    lines: list = text.strip().split("\n")
    ingredients: list = []  # Инициализация списка ингредиентов

    logger.debug(f"Исходный текст: {text}")
    logger.debug(f"Количество строк: {len(lines)}")
    logger.debug(f"Строки: {lines}")

    for line_number, line in enumerate(lines, 1):
        logger.debug(f"Обрабатываем строку {line_number}: {line}")

        # Убираем лишние пробелы
        stripped_line: str = line.strip()

        # Проверяем, если строка начинается с маркера '- ', то это ингредиент
        if stripped_line.startswith("- "):
            # Убираем маркер '- ' и пробелы
            ingredient_name: str = stripped_line[2:].strip()
            # Проверяем, что ингредиент не пустой
            if ingredient_name:
                ingredients.append(ingredient_name)

    logger.debug(f"Парсинг завершен. Найдено ингредиентов: {len(ingredients)}")

    return ingredients
