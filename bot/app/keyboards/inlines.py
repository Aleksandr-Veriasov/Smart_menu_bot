from collections.abc import Callable, Mapping, Sequence

from telegram import (
    InlineKeyboardMarkup,
    WebAppInfo,
)

from bot.app.core.recipes_mode import RecipeMode
from bot.app.keyboards.builders import InlineKB
from bot.app.keyboards.callbacks import HelpCallbacks as HelpCB
from bot.app.keyboards.callbacks import NavCallbacks as NavCB
from bot.app.keyboards.callbacks import RecipeCallbacks as RecipeCB
from bot.app.keyboards.callbacks import SearchCallbacks as SearchCB
from bot.app.keyboards.callbacks import UrlCallbacks as UrlCB
from packages.common_settings.settings import settings


def start_keyboard(new_user: bool) -> InlineKeyboardMarkup:
    """Создание кнопок для стартового сообщения и домой."""
    kb = InlineKB()
    if new_user:
        kb.button(text="📚 Книга рецептов", callback_data=RecipeCB.build_recipes_book())
    else:
        kb.button(text="📖 Мои рецепты", callback_data=RecipeCB.build_recipes_menu(RecipeMode.SHOW))
        kb.button(text="📚 Книга рецептов", callback_data=RecipeCB.build_recipes_book())
        kb.button(text="🎲 Случайные рецепты", callback_data=RecipeCB.build_recipes_menu(RecipeMode.RANDOM))
        kb.button(text="🔍 Поиск рецептов", callback_data=SearchCB.build_search_start())
    kb.button(text="❓ Помощь", callback_data=HelpCB.build_help_show())
    return kb.adjust(1)


def help_keyboard(topic: str | None = None) -> InlineKeyboardMarkup:
    """Создание кнопок для раздела помощи."""
    kb = InlineKB()
    if topic:
        kb.button(text="⬅️ К разделам", callback_data=HelpCB.build_help_show())
        kb.button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
        return kb.adjust(1)
    kb.button(text="📥 Загрузка рецепта", callback_data=HelpCB.build_help_show("upload"))
    kb.button(text="📖 Мои рецепты", callback_data=HelpCB.build_help_show("my_recipes"))
    kb.button(text="📚 Книга рецептов", callback_data=HelpCB.build_help_show("book"))
    kb.button(text="🔍 Поиск рецептов", callback_data=HelpCB.build_help_show("search"))
    kb.button(text="🎲 Случайный рецепт", callback_data=HelpCB.build_help_show("random"))
    kb.button(text="✏️ Редактирование", callback_data=HelpCB.build_help_show("manage"))
    kb.button(text="📤 Поделиться рецептом", callback_data=HelpCB.build_help_show("share"))
    kb.button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
    return kb.adjust(1)


def home_keyboard() -> InlineKeyboardMarkup:
    """Создание кнопок для домашнего меню."""
    return InlineKB().button(text="🏠 На главную", callback_data=NavCB.build_nav_start()).adjust(1)


def random_recipe_keyboard(category_slug: str) -> InlineKeyboardMarkup:
    """Кнопки под случайным рецептом."""
    return (
        InlineKB()
        .button(text="🎲 Еще рецепт", callback_data=RecipeCB.build_recipes_random(category_slug))
        .button(text="📚 Назад к категориям", callback_data=RecipeCB.build_recipes_menu(RecipeMode.RANDOM))
        .button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
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
    kb = InlineKB()

    for cat in categories:
        name = str(cat.get("name") or "").strip()
        slug = str(cat.get("slug") or "").strip().lower()
        if not name or not slug:
            continue
        if callback_builder is not None:
            cb = callback_builder(slug)
        else:
            cb = RecipeCB.build_recipes_category(slug, mode, pipeline_id)
        kb.button(text=name, callback_data=cb)

    if mode is RecipeMode.SAVE:
        kb.button(text="❌ Отмена", callback_data=RecipeCB.build_save_cancel(pipeline_id))
    else:
        kb.button(text="🔙 Назад", callback_data=NavCB.build_nav_start())
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
        callback = RecipeCB.build_recipes_choice(category_slug, suffix, int(recipe["id"]))
        kb.button(text=f'▪️ {recipe["title"]}', callback_data=callback)

    # пагинация
    if end < total:
        kb.button(text="Далее ⏩", callback_data=RecipeCB.build_page(page + 1))
    if page > 0:
        kb.button(text="⏪ Назад", callback_data=RecipeCB.build_page(page - 1))

    if mode is not RecipeMode.SEARCH:  # TODO для поиска сделать возможность повторного поиска
        back_to_categories = categories_callback or RecipeCB.build_recipes_menu(RecipeMode(suffix))
        kb.button(text="📚 К категориям", callback_data=back_to_categories)
    kb.button(text="🏠 В меню", callback_data=NavCB.build_nav_start())

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
        kb.button(text="➕ Добавить к себе", callback_data=RecipeCB.build_recipe_add(recipe_id))
    else:
        if can_manage:
            base = settings.fast_api.base_url()
            webapp_url = f"{base}/webapp/edit-recipe.html?recipe_id={int(recipe_id)}"
            kb.button(text="✏️ Редактировать рецепт", web_app=WebAppInfo(url=webapp_url))
            kb.button(text="🗑 Удалить рецепт", callback_data=RecipeCB.build_recipe_delete(recipe_id))
        kb.button(text="📤 Поделиться рецептом", callback_data=RecipeCB.build_recipe_share(recipe_id))
    kb.button(text="⏪ Назад", callback_data=RecipeCB.build_recipe_back(page, category_slug, mode))
    kb.button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
    return kb.adjust(1)


def keyboard_save() -> InlineKeyboardMarkup:
    """Создание клавиатуры для сохранения изменений."""
    return (
        InlineKB()
        .button(text="✅ Сохранить", callback_data=NavCB.build_edit_save())
        .button(text="❌ Отмена", callback_data=NavCB.build_nav_cancel())
        .adjust(1)
    )


def keyboard_delete() -> InlineKeyboardMarkup:
    """Создание клавиатуры для удаления рецепта."""
    return (
        InlineKB()
        .button(text="🗑 Удалить", callback_data=NavCB.build_nav_delete())
        .button(text="❌ Отмена", callback_data=NavCB.build_nav_cancel())
        .adjust(1)
    )


def keyboard_save_recipe(pipeline_id: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для сохранения рецепта."""
    return (
        InlineKB()
        .button(text="✅ Сохранить рецепт", callback_data=RecipeCB.build_save_start(pipeline_id))
        .button(text="❌ Отмена", callback_data=RecipeCB.build_save_cancel(pipeline_id))
        .adjust(1)
    )


def add_recipe_keyboard(recipe_id: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для добавления рецепта к себе."""
    return (
        InlineKB()
        .button(text="➕ Добавить к себе", callback_data=RecipeCB.build_recipe_add(recipe_id))
        .button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
        .adjust(1)
    )


def share_recipe_keyboard(recipe_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для сообщения со ссылкой на шаринг рецепта."""
    return (
        InlineKB()
        .button(text="⬅️ Назад к рецепту", callback_data=RecipeCB.build_recipe_share_back(recipe_id))
        .button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
        .adjust(1)
    )


def search_recipes_type_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры для выбора типа поиска."""
    return (
        InlineKB()
        .button(text="🔎 По названию", callback_data=SearchCB.build_search_type("title"))
        .button(text="🥦 По ингредиентам", callback_data=SearchCB.build_search_type("ingredient"))
        .button(text="❌ Отмена", callback_data=NavCB.build_nav_cancel())
        .adjust(1)
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопкой отмены."""
    return InlineKB().button(text="❌ Отмена", callback_data=NavCB.build_nav_cancel()).adjust(1)


def url_candidate_list_keyboard(sid: str, recipe_titles: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Клавиатура со списком рецептов, найденных по URL."""
    kb = InlineKB()
    for recipe_id, title in recipe_titles:
        text = (title or "").strip() or "Без названия"
        if len(text) > 45:
            text = text[:42] + "..."
        kb.button(text=f"▪️ {text}", callback_data=UrlCB.build_url_pick(sid, int(recipe_id)))
    kb.button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
    return kb.adjust(1)


def url_candidate_recipe_keyboard(*, sid: str, recipe_id: int, already_linked: bool) -> InlineKeyboardMarkup:
    """Клавиатура карточки рецепта, открытого из списка кандидатов по URL."""
    kb = InlineKB()
    if not already_linked:
        kb.button(text="➕ Добавить к себе", callback_data=UrlCB.build_url_add(sid, recipe_id))
    kb.button(text="⬅️ Назад к списку", callback_data=UrlCB.build_url_list(sid))
    kb.button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
    return kb.adjust(1)


def url_candidate_category_keyboard(
    sid: str,
    recipe_id: int,
    categories: Sequence[Mapping[str, object]],
) -> InlineKeyboardMarkup:
    """Клавиатура выбора категории для добавления рецепта из списка кандидатов по URL."""
    kb = InlineKB()
    for category in categories:
        name = str(category.get("name") or "").strip()
        slug = str(category.get("slug") or "").strip().lower()
        if not name or not slug:
            continue
        kb.button(text=name, callback_data=UrlCB.build_url_add_category(sid, recipe_id, slug))
    kb.button(text="⬅️ Назад к списку", callback_data=UrlCB.build_url_list(sid))
    kb.button(text="🏠 На главную", callback_data=NavCB.build_nav_start())
    return kb.adjust(1)
