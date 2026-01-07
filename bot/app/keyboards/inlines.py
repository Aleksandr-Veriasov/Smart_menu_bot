from collections.abc import Callable

from telegram import (
    InlineKeyboardMarkup,
)

from bot.app.core.recipes_mode import RecipeMode
from bot.app.keyboards.builders import InlineKB
from packages.common_settings.settings import settings


def start_keyboard(new_user: bool) -> InlineKeyboardMarkup:
    """Создание кнопок для стартового сообщения и домой."""
    kb = InlineKB()
    if new_user:
        kb.button(text="🍳 Загрузить рецепт", callback_data="upload_recipe")
        kb.button(text="❓ Помощь", callback_data="help")
    else:
        kb.button(text="📖 Рецепты", callback_data="recipes_show")
        kb.button(text="🎲 Случайные рецепты", callback_data="recipes_random")
        kb.button(text="🍳 Загрузить рецепт", callback_data="upload_recipe")
        kb.button(text="✏️ Редактировать рецепт", callback_data="recipes_edit")
    return kb.adjust(1)


def help_keyboard() -> InlineKeyboardMarkup:
    """Создание кнопок для помощи."""
    return (
        InlineKB()
        .button(text="🏠 На главную", callback_data="start")
        .button(text="🍳 Загрузить рецепт", callback_data="upload_recipe")
        .adjust(1)
    )


def home_keyboard() -> InlineKeyboardMarkup:
    """Создание кнопок для домашнего меню."""
    return InlineKB().button(text="🏠 На главную", callback_data="start").adjust(1)


def category_keyboard(
    categories: list[dict[str, str]],
    mode: RecipeMode = RecipeMode.SHOW,
    pipeline_id: int = 0,
    *,
    callback_builder: Callable[[str], str] | None = None,
) -> InlineKeyboardMarkup:
    """Создание кнопок для выбора категории рецептов."""
    suffix = mode.value
    kb = InlineKB()

    for cat in categories:
        name = (cat.get("name") or "").strip()
        slug = (cat.get("slug") or "").strip().lower()
        if not name or not slug:
            continue
        if callback_builder is not None:
            cb = callback_builder(slug)
        else:
            cb = f"{slug}_{suffix}:{pipeline_id}" if mode is RecipeMode.SAVE else f"{slug}_{suffix}"
        kb.button(text=name, callback_data=cb)

    if mode is RecipeMode.SAVE:
        kb.button(text="❌ Отмена", callback_data="cancel_save_recipe")
    else:
        kb.button(text="🔙 Назад", callback_data="start")
    return kb.adjust(1)


def build_recipes_list_keyboard(
    items: list[dict[str, int | str]],
    page: int = 0,
    *,
    per_page: int = settings.telegram.recipes_per_page,
    category_slug: str,
    mode: RecipeMode = RecipeMode.SHOW,
) -> InlineKeyboardMarkup:
    """Создание клавиатуры для списка рецептов с пагинацией."""
    total = len(items)
    start = max(0, page) * per_page
    end = min(total, start + per_page)
    current = items[start:end]
    suffix = mode.value
    kb = InlineKB()

    for recipe in current:
        callback = f'{category_slug}_{suffix}_{recipe["id"]}'
        kb.button(text=f'▪️ {recipe["title"]}', callback_data=callback)

    # пагинация
    if end < total:
        kb.button(text="Далее ⏩", callback_data=f"next_{page + 1}")
    if page > 0:
        kb.button(text="⏪ Назад", callback_data=f"prev_{page - 1}")

    # домой/меню (если нужно)
    kb.button(text="📚 К категориям", callback_data=f"recipes_{suffix}")
    kb.button(text="🏠 В меню", callback_data="start")

    return kb.adjust(1)


def recipe_edit_keyboard(recipe_id: int, page: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для редактирования рецепта."""
    return (
        InlineKB()
        # .button(text="✏️ Редактировать рецепт", callback_data=f"edit_recipe_{recipe_id}")
        .button(text="🗑 Удалить рецепт", callback_data=f"delete_recipe_{recipe_id}")
        .button(text="🔄 Изменить категорию", callback_data=f"change_category_{recipe_id}")
        .button(text="⏪ Назад", callback_data=f"next_{page}")
        .button(text="🏠 На главную", callback_data="start")
        .adjust(1)
    )


def choice_recipe_keyboard(page: int, recipe_id: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для выбора рецепта."""
    return (
        InlineKB()
        .button(text="⏪ Назад", callback_data=f"next_{page}")
        .button(text="📤 Поделиться рецептом", callback_data=f"share_recipe_{recipe_id}")
        .button(text="🏠 На главную", callback_data="start")
        .adjust(1)
    )


def keyboard_choose_field() -> InlineKeyboardMarkup:
    """Создание клавиатуры для выбора поля для редактирования."""
    return (
        InlineKB()
        .button(text="📝 Изменить название", callback_data="f:title")
        .button(text="❌ Отмена", callback_data="cancel")
        .adjust(1)
    )


def keyboard_save() -> InlineKeyboardMarkup:
    """Создание клавиатуры для сохранения изменений."""
    return (
        InlineKB()
        .button(text="✅ Сохранить", callback_data="save_changes")
        .button(text="❌ Отмена", callback_data="cancel")
        .adjust(1)
    )


def keyboard_delete() -> InlineKeyboardMarkup:
    """Создание клавиатуры для удаления рецепта."""
    return (
        InlineKB()
        .button(text="🗑 Удалить", callback_data="delete")
        .button(text="❌ Отмена", callback_data="cancel")
        .adjust(1)
    )


def keyboard_save_cancel_delete(func: str = "") -> InlineKeyboardMarkup:
    """Создание клавиатуры для сохранения, отмены и удаления."""
    kb = InlineKB()
    if func == "start_edit":
        kb.button(text="📝 Изменить название", callback_data="f:title")
    elif func == "handle_title":
        kb.button(text="✅ Сохранить", callback_data="save_changes")
    elif func == "delete_recipe":
        kb.button(text="🗑 Удалить", callback_data="delete")
    kb.button(text="❌ Отмена", callback_data="cancel")
    return kb.adjust(1)


def keyboard_save_recipe(pipeline_id: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для сохранения рецепта."""
    return (
        InlineKB()
        .button(text="✅ Сохранить рецепт", callback_data=f"save_recipe:{pipeline_id}")
        .button(text="❌ Отмена", callback_data=f"cancel_save_recipe:{pipeline_id}")
        .adjust(1)
    )


def add_recipe_keyboard(recipe_id: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для добавления рецепта к себе."""
    return (
        InlineKB()
        .button(text="➕ Добавить к себе", callback_data=f"add_recipe:{recipe_id}")
        .button(text="🏠 На главную", callback_data="start")
        .adjust(1)
    )
