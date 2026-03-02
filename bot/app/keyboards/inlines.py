from collections.abc import Callable, Mapping, Sequence

from telegram import (
    InlineKeyboardMarkup,
    WebAppInfo,
)

from bot.app.core.recipes_mode import RecipeMode
from bot.app.keyboards.builders import InlineKB
from packages.common_settings.settings import settings


def start_keyboard(new_user: bool) -> InlineKeyboardMarkup:
    """Создание кнопок для стартового сообщения и домой."""
    kb = InlineKB()
    if new_user:
        kb.button(text="📚 Книга рецептов", callback_data="recipes_book")
    else:
        kb.button(text="📖 Мои рецепты", callback_data="recipes_show")
        kb.button(text="📚 Книга рецептов", callback_data="recipes_book")
        kb.button(text="🎲 Случайные рецепты", callback_data="recipes_random")
        kb.button(text="🔍 Поиск рецептов", callback_data="search_recipes")
    kb.button(text="❓ Помощь", callback_data="help")
    return kb.adjust(1)


def help_keyboard(topic: str | None = None) -> InlineKeyboardMarkup:
    """Создание кнопок для раздела помощи."""
    kb = InlineKB()
    if topic:
        kb.button(text="⬅️ К разделам", callback_data="help")
        kb.button(text="🏠 На главную", callback_data="start")
        return kb.adjust(1)
    kb.button(text="📥 Загрузка рецепта", callback_data="help:upload")
    kb.button(text="📖 Мои рецепты", callback_data="help:my_recipes")
    kb.button(text="📚 Книга рецептов", callback_data="help:book")
    kb.button(text="🔍 Поиск рецептов", callback_data="help:search")
    kb.button(text="🎲 Случайный рецепт", callback_data="help:random")
    kb.button(text="✏️ Редактирование", callback_data="help:manage")
    kb.button(text="📤 Поделиться рецептом", callback_data="help:share")
    kb.button(text="🏠 На главную", callback_data="start")
    return kb.adjust(1)


def home_keyboard() -> InlineKeyboardMarkup:
    """Создание кнопок для домашнего меню."""
    return InlineKB().button(text="🏠 На главную", callback_data="start").adjust(1)


def random_recipe_keyboard(category_slug: str) -> InlineKeyboardMarkup:
    """Кнопки под случайным рецептом."""
    return (
        InlineKB()
        .button(text="🎲 Еще рецепт", callback_data=f"{category_slug}_random")
        .button(text="📚 Назад к категориям", callback_data="recipes_random")
        .button(text="🏠 На главную", callback_data="start")
        .adjust(1)
    )


def category_keyboard(
    categories: Sequence[Mapping[str, object]],
    mode: RecipeMode = RecipeMode.SHOW,
    pipeline_id: int = 0,
    *,
    callback_builder: Callable[[str], str] | None = None,
) -> InlineKeyboardMarkup:
    """Создание кнопок для выбора категории рецептов."""
    suffix = mode.value
    kb = InlineKB()

    for cat in categories:
        name = str(cat.get("name") or "").strip()
        slug = str(cat.get("slug") or "").strip().lower()
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
    categories_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """Создание клавиатуры для списка рецептов с пагинацией."""
    total = len(items)
    start = max(0, page) * per_page
    end = min(total, start + per_page)
    current = items[start:end]
    suffix = RecipeMode.SHOW.value if mode is RecipeMode.SEARCH else mode.value
    kb = InlineKB()

    for recipe in current:
        callback = f'{category_slug}_{suffix}_{recipe["id"]}'
        kb.button(text=f'▪️ {recipe["title"]}', callback_data=callback)

    # пагинация
    if end < total:
        kb.button(text="Далее ⏩", callback_data=f"next_{page + 1}")
    if page > 0:
        kb.button(text="⏪ Назад", callback_data=f"prev_{page - 1}")

    if mode is not RecipeMode.SEARCH:  # TODO для поиска сделать возможность повторного поиска
        back_to_categories = categories_callback or f"recipes_{suffix}"
        kb.button(text="📚 К категориям", callback_data=back_to_categories)
    kb.button(text="🏠 В меню", callback_data="start")

    return kb.adjust(1)


def choice_recipe_keyboard(
    recipe_id: int,
    page: int,
    category_slug: str,
    mode: str,
    *,
    add_to_self: bool = False,
    can_manage: bool = False,
) -> InlineKeyboardMarkup:
    """Создание клавиатуры для выбора рецепта."""
    kb = InlineKB()
    if add_to_self:
        kb.button(text="➕ Добавить к себе", callback_data=f"add_recipe:{recipe_id}")
    else:
        if can_manage:
            base = settings.fast_api.base_url()
            webapp_url = f"{base}/webapp/edit-recipe.html?recipe_id={int(recipe_id)}"
            kb.button(text="✏️ Редактировать рецепт", web_app=WebAppInfo(url=webapp_url))
            kb.button(text="🗑 Удалить рецепт", callback_data=f"delete_recipe_{recipe_id}")
        kb.button(text="📤 Поделиться рецептом", callback_data=f"share_recipe_{recipe_id}")
    kb.button(text="⏪ Назад", callback_data=f"next_{page}:{category_slug}:{mode}")
    kb.button(text="🏠 На главную", callback_data="start")
    return kb.adjust(1)


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


def search_recipes_type_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры для выбора типа поиска."""
    return (
        InlineKB()
        .button(text="🔎 По названию", callback_data="search:title")
        .button(text="🥦 По ингредиентам", callback_data="search:ingredient")
        .button(text="❌ Отмена", callback_data="cancel")
        .adjust(1)
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопкой отмены."""
    return InlineKB().button(text="❌ Отмена", callback_data="cancel").adjust(1)
