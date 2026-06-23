"""Клавиатуры карточек рецептов, списков, шаринга, сохранения и выбора по ссылке."""

from collections.abc import Mapping, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.src.keyboards.callback_data import (
    AddCatCB,
    BookCatCB,
    CatCB,
    ChoiceCB,
    MenuCB,
    NavCB,
    PageCB,
    RecipeCB,
    SaveCB,
    SearchTypeCB,
    UrlCB,
)
from bot.src.recipe_flow.modes import RecipeMode
from packages.common_settings.settings import settings


def add_recipe_keyboard(recipe_id: int) -> InlineKeyboardMarkup:
    """Карточка рецепта по deep-link/каталогу: добавить к себе / на главную."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить к себе", callback_data=RecipeCB(action="add", recipe_id=recipe_id))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def share_recipe_keyboard(recipe_id: int) -> InlineKeyboardMarkup:
    """Сообщение со ссылкой на шаринг рецепта."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад к рецепту", callback_data=RecipeCB(action="shareback", recipe_id=recipe_id))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def choice_recipe_keyboard(
    recipe_id: int,
    page: int,
    category_slug: str,
    mode: str,
    *,
    add_to_self: bool = False,
    can_manage: bool = False,
) -> InlineKeyboardMarkup:
    """Клавиатура карточки рецепта в списке."""
    builder = InlineKeyboardBuilder()
    if add_to_self:
        builder.button(text="➕ Добавить к себе", callback_data=RecipeCB(action="add", recipe_id=recipe_id))
    else:
        if can_manage:
            base = settings.fast_api.base_url()
            webapp_url = f"{base}/webapp/edit-recipe.html?recipe_id={int(recipe_id)}"
            builder.button(text="✏️ Редактировать рецепт", web_app=WebAppInfo(url=webapp_url))
            builder.button(text="🗑 Удалить рецепт", callback_data=RecipeCB(action="delete", recipe_id=recipe_id))
        builder.button(text="📤 Поделиться рецептом", callback_data=RecipeCB(action="share", recipe_id=recipe_id))
    builder.button(text="⏪ Назад", callback_data=PageCB(page=page, category=category_slug, mode=mode))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def save_recipe_keyboard(pipeline_id: int) -> InlineKeyboardMarkup:
    """Подтверждение сохранения распознанного рецепта."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Сохранить рецепт", callback_data=SaveCB(action="start", pipeline_id=pipeline_id))
    builder.button(text="❌ Отмена", callback_data=SaveCB(action="cancel", pipeline_id=pipeline_id))
    builder.adjust(1)
    return builder.as_markup()


def url_candidate_list_keyboard(sid: str, recipe_titles: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """Список рецептов, найденных по одной ссылке."""
    builder = InlineKeyboardBuilder()
    for recipe_id, title in recipe_titles:
        text = (title or "").strip() or "Без названия"
        if len(text) > 45:
            text = text[:42] + "..."
        builder.button(text=f"▪️ {text}", callback_data=UrlCB(action="pick", sid=sid, recipe_id=int(recipe_id)))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def url_candidate_recipe_keyboard(*, sid: str, recipe_id: int, already_linked: bool) -> InlineKeyboardMarkup:
    """Карточка рецепта, открытого из списка кандидатов по ссылке."""
    builder = InlineKeyboardBuilder()
    if not already_linked:
        builder.button(text="➕ Добавить к себе", callback_data=UrlCB(action="add", sid=sid, recipe_id=recipe_id))
    builder.button(text="⬅️ Назад к списку", callback_data=UrlCB(action="list", sid=sid))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def url_candidate_category_keyboard(
    sid: str,
    recipe_id: int,
    categories: Sequence[Mapping[str, object]],
) -> InlineKeyboardMarkup:
    """Выбор категории для добавления рецепта из списка кандидатов по ссылке."""
    builder = InlineKeyboardBuilder()
    for category in categories:
        name = str(category.get("name") or "").strip()
        slug = str(category.get("slug") or "").strip().lower()
        if not name or not slug:
            continue
        builder.button(
            text=name,
            callback_data=UrlCB(action="addcat", sid=sid, recipe_id=recipe_id, slug=slug),
        )
    builder.button(text="⬅️ Назад к списку", callback_data=UrlCB(action="list", sid=sid))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def random_recipe_keyboard(category_slug: str) -> InlineKeyboardMarkup:
    """Кнопки под случайным рецептом."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Еще рецепт", callback_data=CatCB(slug=category_slug, mode="random"))
    builder.button(text="📚 Назад к категориям", callback_data=MenuCB(mode="random"))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def _fill_categories(
    builder: InlineKeyboardBuilder,
    categories: Sequence[Mapping[str, object]],
    callback_for_slug,
) -> None:
    """Добавляет кнопки категорий (slug → CallbackData)."""
    for category in categories:
        name = str(category.get("name") or "").strip()
        slug = str(category.get("slug") or "").strip().lower()
        if not name or not slug:
            continue
        builder.button(text=name, callback_data=callback_for_slug(slug))


def categories_menu_keyboard(categories: Sequence[Mapping[str, object]], mode: RecipeMode) -> InlineKeyboardMarkup:
    """Категории «Мои рецепты»/«Случайные»."""
    builder = InlineKeyboardBuilder()
    _fill_categories(builder, categories, lambda slug: CatCB(slug=slug, mode=mode.value))
    builder.button(text="🔙 Назад", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def categories_book_keyboard(categories: Sequence[Mapping[str, object]]) -> InlineKeyboardMarkup:
    """Категории книги рецептов."""
    builder = InlineKeyboardBuilder()
    _fill_categories(builder, categories, lambda slug: BookCatCB(slug=slug))
    builder.button(text="🔙 Назад", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def categories_save_keyboard(categories: Sequence[Mapping[str, object]], pipeline_id: int) -> InlineKeyboardMarkup:
    """Выбор категории при сохранении распознанного рецепта."""
    builder = InlineKeyboardBuilder()
    _fill_categories(builder, categories, lambda slug: CatCB(slug=slug, mode="save", pipeline_id=pipeline_id))
    builder.button(text="❌ Отмена", callback_data=SaveCB(action="cancel", pipeline_id=pipeline_id))
    builder.adjust(1)
    return builder.as_markup()


def categories_add_keyboard(categories: Sequence[Mapping[str, object]], recipe_id: int) -> InlineKeyboardMarkup:
    """Выбор категории при добавлении существующего рецепта к себе."""
    builder = InlineKeyboardBuilder()
    _fill_categories(builder, categories, lambda slug: AddCatCB(recipe_id=recipe_id, slug=slug))
    builder.button(text="🔙 Назад", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def recipes_list_keyboard(
    items: list[dict[str, int | str]],
    page: int = 0,
    *,
    per_page: int = settings.telegram.recipes_per_page,
    category_slug: str,
    mode: RecipeMode = RecipeMode.SHOW,
    categories_callback: CallbackData | None = None,
) -> InlineKeyboardMarkup:
    """Список рецептов с пагинацией."""
    total = len(items)
    start = max(0, page) * per_page
    end = min(total, start + per_page)
    current = items[start:end]
    suffix = RecipeMode.SHOW.value if mode is RecipeMode.SEARCH else mode.value
    builder = InlineKeyboardBuilder()

    for recipe in current:
        builder.button(
            text=f'▪️ {recipe["title"]}',
            callback_data=ChoiceCB(category=category_slug, mode=suffix, recipe_id=int(recipe["id"])),
        )

    if end < total:
        builder.button(text="Далее ⏩", callback_data=PageCB(page=page + 1))
    if page > 0:
        builder.button(text="⏪ Назад", callback_data=PageCB(page=page - 1))

    if mode is not RecipeMode.SEARCH:
        back = categories_callback or MenuCB(mode=suffix)
        builder.button(text="📚 К категориям", callback_data=back)
    builder.button(text="🏠 В меню", callback_data=NavCB(action="start"))

    builder.adjust(1)
    return builder.as_markup()


def search_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа поиска."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔎 По названию", callback_data=SearchTypeCB(kind="title"))
    builder.button(text="🥦 По ингредиентам", callback_data=SearchTypeCB(kind="ingredient"))
    builder.button(text="❌ Отмена", callback_data=NavCB(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=NavCB(action="cancel"))
    return builder.as_markup()


def delete_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение удаления рецепта."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Удалить", callback_data=NavCB(action="delete"))
    builder.button(text="❌ Отмена", callback_data=NavCB(action="cancel"))
    builder.adjust(1)
    return builder.as_markup()
