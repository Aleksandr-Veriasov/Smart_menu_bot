from packages.recipes_core.services.provider import get_default_extractor


async def extract_recipes(
    description: str, transcript: str
) -> tuple[str, str, str]:
    """
    Извлекает название, текст рецепта и ингредиенты из описания и транскрипта.
    """
    extractor = get_default_extractor()
    data = await extractor.extract(
        description=description, recognized_text=transcript
    )
    return data.title, data.instructions_text, data.ingredients_text
