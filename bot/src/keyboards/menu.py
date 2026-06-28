"""Навигационные клавиатуры (старт/справка/домой) на InlineKeyboardBuilder + CallbackData."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.src.keyboards.callback_data import BookCB, HelpCB, MenuCB, NavCB, SearchCB


def start_keyboard(new_user: bool) -> InlineKeyboardMarkup:
    """Кнопки стартового сообщения."""
    builder = InlineKeyboardBuilder()
    if new_user:
        builder.button(text="📚 Книга рецептов", callback_data=BookCB())
    else:
        builder.button(text="📖 Мои рецепты", callback_data=MenuCB(mode="show"))
        builder.button(text="📚 Книга рецептов", callback_data=BookCB())
        builder.button(text="🎲 Случайные рецепты", callback_data=MenuCB(mode="random"))
        builder.button(text="🔍 Поиск рецептов", callback_data=SearchCB(action="start"))
    builder.button(text="❓ Помощь", callback_data=HelpCB(topic="show"))
    builder.adjust(1)
    return builder.as_markup()


def help_keyboard(topic: str | None = None) -> InlineKeyboardMarkup:
    """Кнопки раздела помощи."""
    builder = InlineKeyboardBuilder()
    if topic:
        builder.button(text="⬅️ К разделам", callback_data=HelpCB(topic="show"))
        builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
        builder.adjust(1)
        return builder.as_markup()

    builder.button(text="📥 Загрузка рецепта", callback_data=HelpCB(topic="upload"))
    builder.button(text="📖 Мои рецепты", callback_data=HelpCB(topic="my_recipes"))
    builder.button(text="📚 Книга рецептов", callback_data=HelpCB(topic="book"))
    builder.button(text="🔍 Поиск рецептов", callback_data=HelpCB(topic="search"))
    builder.button(text="🎲 Случайный рецепт", callback_data=HelpCB(topic="random"))
    builder.button(text="✏️ Редактирование", callback_data=HelpCB(topic="manage"))
    builder.button(text="📤 Поделиться рецептом", callback_data=HelpCB(topic="share"))
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    builder.adjust(1)
    return builder.as_markup()


def home_keyboard() -> InlineKeyboardMarkup:
    """Единственная кнопка «На главную»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 На главную", callback_data=NavCB(action="start"))
    return builder.as_markup()
