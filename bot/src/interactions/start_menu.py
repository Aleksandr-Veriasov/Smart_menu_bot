from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import Message, User

from bot.src.bot_ui.messages import MessageService
from bot.src.keyboards.menu import start_keyboard
from bot.src.texts.user import render_start_text


async def show_start_menu(
    target_message: Message,
    tg_user: User,
    *,
    bot: Bot,
    message_service: MessageService,
    recipe_count: int | None,
) -> None:
    """Показывает стартовое меню."""

    new_user = recipe_count == 0
    text = render_start_text(tg_user, new_user=new_user)

    await message_service.delete_tracked_messages(bot, chat_id=target_message.chat.id)
    await message_service.send_and_track(
        bot,
        chat_id=target_message.chat.id,
        text=text,
        reply_markup=start_keyboard(new_user),
        parse_mode=ParseMode.HTML,
    )
