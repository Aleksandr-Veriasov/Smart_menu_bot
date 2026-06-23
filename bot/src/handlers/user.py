import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.src.bot_ui.messages import MessageService
from bot.src.interactions.shared_recipe import show_shared_recipe
from bot.src.interactions.start_menu import show_start_menu
from bot.src.keyboards.callback_data import HelpCB, NavCB
from bot.src.keyboards.menu import help_keyboard
from bot.src.texts.user import render_help_text
from bot.src.utils.deep_link import parse_shared_token
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="user")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    user: User,
    user_recipe_count: int | None,
    bot: Bot,
    message_service: MessageService,
    recipe_service: RecipeService,
) -> None:
    """/start — стартовое меню, в т.ч. deep-link шаринга рецептов."""
    await state.clear()

    token = parse_shared_token(command.args)
    if token and await show_shared_recipe(message, recipe_service, message_service, token):
        return

    await show_start_menu(
        message,
        user,
        bot=bot,
        message_service=message_service,
        recipe_count=user_recipe_count,
    )


@router.callback_query(NavCB.filter(F.action == "start"))
async def cb_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    user_recipe_count: int | None,
    bot: Bot,
    message_service: MessageService,
) -> None:
    """Кнопка «На главную» — возврат в стартовое меню."""
    await callback.answer()
    await state.clear()
    if not isinstance(callback.message, Message):
        return
    await show_start_menu(
        callback.message,
        user,
        bot=bot,
        message_service=message_service,
        recipe_count=user_recipe_count,
    )


@router.message(Command("help"))
async def cmd_help(message: Message, message_service: MessageService) -> None:
    """/help — корневой раздел справки."""
    text, topic = render_help_text(None)
    await message_service.answer_and_track(
        message,
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=help_keyboard(topic),
    )


@router.callback_query(HelpCB.filter())
async def cb_help(
    callback: CallbackQuery,
    callback_data: HelpCB,
    message_service: MessageService,
) -> None:
    """Инлайн-кнопка «Помощь» и разделы справки."""
    await callback.answer()
    text, topic = render_help_text(callback_data.topic)
    keyboard = help_keyboard(topic)

    if isinstance(callback.message, Message):
        await message_service.safe_edit(
            callback.message,
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
