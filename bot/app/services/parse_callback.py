from bot.app.core.recipes_mode import RecipeMode
from bot.app.keyboards.callbacks import RecipeCallbacks


def parse_category_mode(cb: str) -> tuple[str, RecipeMode] | None:
    """
    Возвращает (category_slug, mode) или None, если формат не подошёл.
    """
    return RecipeCallbacks.parse_category_mode(cb)


def parse_category(cb: str) -> str | None:
    """
    Возвращает (category_slug) или None, если формат не подошёл.
    """
    parsed = RecipeCallbacks.parse_save_category(cb)
    return parsed[0] if parsed else None


def parse_mode(cb: str) -> RecipeMode | None:
    """
    Возвращает (mode) или None, если формат не подошёл.
    """
    return RecipeCallbacks.parse_recipes_menu_mode(cb)


def parse_category_mode_id(cb: str) -> tuple[str, str, int] | None:
    """
    Возвращает (category, mode, obj_id) или None, если формат не подошёл.
    mode: 'show' | 'random'
    """
    return RecipeCallbacks.parse_recipe_choice(cb)


#
# change_category:* больше не используем: редактирование переехало в WebApp
#
