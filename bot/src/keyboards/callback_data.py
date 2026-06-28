"""Типизированные CallbackData-фабрики (идиоматичный aiogram).

Заменяют строковые callback-классы + regex + ручные `parse_*`. Хендлеры
фильтруются через `XxxCB.filter(...)` и получают распарсенный объект в
аргументе `callback_data`.
"""

from aiogram.filters.callback_data import CallbackData


class NavCB(CallbackData, prefix="nav"):  # type: ignore[call-arg]
    """Навигация: домой/отмена/удаление. Пакуется в `nav:<action>`."""

    action: str  # start | cancel | delete


class HelpCB(CallbackData, prefix="help"):  # type: ignore[call-arg]
    """Разделы справки. `topic="show"` — корневой список разделов."""

    topic: str = "show"


class MenuCB(CallbackData, prefix="menu"):  # type: ignore[call-arg]
    """Меню «Мои рецепты» / «Случайные рецепты»."""

    mode: str  # show | random


class BookCB(CallbackData, prefix="book"):  # type: ignore[call-arg]
    """Книга рецептов (общий каталог)."""


class SearchCB(CallbackData, prefix="search"):  # type: ignore[call-arg]
    """Поиск рецептов."""

    action: str = "start"


class RecipeCB(CallbackData, prefix="recipe"):  # type: ignore[call-arg]
    """Действия над конкретным рецептом."""

    action: str  # add | share | shareback | delete
    recipe_id: int


class SaveCB(CallbackData, prefix="save"):  # type: ignore[call-arg]
    """Сохранение черновика рецепта в категорию."""

    action: str  # start | cancel
    pipeline_id: int


class PageCB(CallbackData, prefix="page"):  # type: ignore[call-arg]
    """Пагинация списка рецептов (category/mode пустые — список без категории)."""

    page: int
    category: str = ""
    mode: str = ""


class UrlCB(CallbackData, prefix="url"):  # type: ignore[call-arg]
    """Выбор рецепта, когда по одной ссылке найдено несколько кандидатов."""

    action: str  # pick | list | add | addcat
    sid: str
    recipe_id: int = 0
    slug: str = ""


class BookCatCB(CallbackData, prefix="bookcat"):  # type: ignore[call-arg]
    """Категория книги рецептов."""

    slug: str


class CatCB(CallbackData, prefix="cat"):  # type: ignore[call-arg]
    """Категория рецептов. mode: show | random | save (для save указывается pipeline_id)."""

    slug: str
    mode: str
    pipeline_id: int = 0


class ChoiceCB(CallbackData, prefix="choice"):  # type: ignore[call-arg]
    """Выбор конкретного рецепта из списка."""

    category: str
    mode: str
    recipe_id: int


class AddCatCB(CallbackData, prefix="addcat"):  # type: ignore[call-arg]
    """Добавление рецепта к себе с выбором категории."""

    recipe_id: int
    slug: str


class SearchTypeCB(CallbackData, prefix="stype"):  # type: ignore[call-arg]
    """Тип поиска рецептов."""

    kind: str  # title | ingredient
