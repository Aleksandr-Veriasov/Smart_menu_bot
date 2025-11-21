import logging
from typing import List

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.app.core.recipes_mode import RecipeMode
from bot.app.keyboards.builders import InlineKB

logger = logging.getLogger(__name__)


def start_keyboard(new_user: bool) -> InlineKeyboardMarkup:
    """Создание кнопок для стартового сообщения и домой."""
    if new_user:
        keyboard = [
            [
                InlineKeyboardButton(
                    "🍳 Загрузить рецепт", callback_data="upload_recipe"
                )
            ],
            [InlineKeyboardButton("❓ Помощь", callback_data="help")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("📖 Рецепты", callback_data="recipes_show")],
            [
                InlineKeyboardButton(
                    "🎲 Случайные рецепты", callback_data="recipes_random"
                )
            ],
            [
                InlineKeyboardButton(
                    "🍳 Загрузить рецепт", callback_data="upload_recipe"
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Редактировать рецепт", callback_data="recipes_edit"
                )
            ],
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup


def help_keyboard() -> InlineKeyboardMarkup:
    """Создание кнопок для помощи."""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏠 На главную", callback_data="start")],
            [
                InlineKeyboardButton(
                    "🍳 Загрузить рецепт", callback_data="upload_recipe"
                )
            ],
        ]
    )
    return keyboard


def home_keyboard() -> InlineKeyboardMarkup:
    """Создание кнопок для домашнего меню."""
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 На главную", callback_data="start")]]
    )
    return keyboard


def category_keyboard(
    categories: List[dict[str, str]],
    mode: RecipeMode = RecipeMode.SHOW,
    pipeline_id: int = 0,
) -> InlineKeyboardMarkup:
    """Создание кнопок для выбора категории рецептов."""
    suffix = mode.value
    rows: list[list[InlineKeyboardButton]] = []

    for cat in categories:
        name = (cat.get("name") or "").strip()
        slug = (cat.get("slug") or "").strip().lower()
        if not name or not slug:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    name,
                    callback_data=(
                        f"{slug}_{suffix}:{pipeline_id}"
                        if mode is RecipeMode.SAVE
                        else f"{slug}_{suffix}"
                    ),
                )
            ]
        )
    if mode is RecipeMode.SAVE:
        rows.append(
            [
                InlineKeyboardButton(
                    "❌ Отмена", callback_data="cancel_save_recipe"
                )
            ]
        )
    else:
        rows.append([InlineKeyboardButton("🔙 Назад", callback_data="start")])
    reply_markup = InlineKeyboardMarkup(rows)
    return reply_markup


def build_recipes_list_keyboard(
    items: List[dict[str, int | str]],
    page: int = 0,
    *,
    per_page: int = 5,
    edit: bool = False,
    category_slug: str,
    mode: RecipeMode = RecipeMode.SHOW,
) -> InlineKeyboardMarkup:
    """Создание клавиатуры для списка рецептов с пагинацией."""
    total = len(items)
    start = max(0, page) * per_page
    end = min(total, start + per_page)
    current = items[start:end]
    suffix = mode.value

    rows = []
    for recipe in current:
        callback = f'{category_slug}_{suffix}_{recipe["id"]}'

        button = InlineKeyboardButton(
            text=f'▪️ {recipe["title"]}',
            callback_data=callback,
        )

        rows.append([button])

    # пагинация
    if end < total:
        rows.append(
            [InlineKeyboardButton("Далее ⏩", callback_data=f"next_{page + 1}")]
        )
    if page > 0:
        rows.append(
            [InlineKeyboardButton("⏪ Назад", callback_data=f"prev_{page - 1}")]
        )

    # домой/меню (если нужно)
    rows.append([InlineKeyboardButton("🏠 В меню", callback_data="start")])

    return InlineKeyboardMarkup(rows)


def recipe_edit_keyboard(recipe_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ Редактировать рецепт",
                    callback_data=f"edit_recipe_{recipe_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑 Удалить рецепт",
                    callback_data=f"delete_recipe_{recipe_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Изменить категорию",
                    callback_data=f"change_category_{recipe_id}",
                )
            ],
            [InlineKeyboardButton("⏪ Назад", callback_data=f"next_{page}")],
            [InlineKeyboardButton("🏠 На главную", callback_data="start")],
        ]
    )


def choice_recipe_keyboard(page: int) -> InlineKeyboardMarkup:
    """Создание клавиатуры для выбора рецепта."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏪ Назад", callback_data=f"next_{page}")],
            [InlineKeyboardButton("🏠 На главную", callback_data="start")],
        ]
    )


def keyboard_choose_field() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📝 Изменить название", callback_data="f:title"
                )
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
        ]
    )


def keyboard_save() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Сохранить", callback_data="save_changes"
                )
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
        ]
    )


def keyboard_delete() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑 Удалить", callback_data="delete")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
        ]
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
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Сохранить рецепт",
                    callback_data=f"save_recipe:{pipeline_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data=f"cancel_save_recipe:{pipeline_id}",
                )
            ],
        ]
    )
