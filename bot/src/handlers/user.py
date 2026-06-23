import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User
from redis.asyncio import Redis

from bot.src.keyboards.callback_data import HelpCB, NavCB
from bot.src.keyboards.menu import help_keyboard, start_keyboard
from bot.src.keyboards.recipe import add_recipe_keyboard
from bot.src.messages.user import (
    HELP_TEXT,
    HELP_TOPICS,
    START_TEXT_NEW_USER,
    START_TEXT_USER,
)
from bot.src.utils.messaging import (
    answer_and_track,
    answer_video_and_track,
    delete_tracked_messages,
    safe_edit,
    send_and_track,
)
from bot.src.utils.recipe_text import build_existing_recipe_text
from bot.src.utils.share_token import decrypt_recipe_id
from packages.db.schemas import UserCreate
from packages.redis.repository import RecipeActionCacheRepository
from packages.services.recipe_service import RecipeService
from packages.services.user_service import UserService

logger = logging.getLogger(__name__)

router = Router(name="user")


# Telegram deep-link `start` payloads: `share_<token>` (и легаси `share:<token>`).
_SHARE_PREFIXES = ("share_", "share:")


def _parse_shared_token(args: str | None) -> str | None:
    """Извлекает токен шаринга из payload команды /start."""
    if not args:
        return None
    for prefix in _SHARE_PREFIXES:
        if args.startswith(prefix):
            return args.removeprefix(prefix).strip() or None
    return None


async def handle_shared_start(
    message: Message,
    recipe_service: RecipeService,
    redis: Redis,
    token: str,
) -> bool:
    """Показывает рецепт по deep-link-токену. Возвращает True, если рецепт найден."""
    recipe_id = decrypt_recipe_id(token)
    if not recipe_id or not recipe_id.isdigit():
        return False

    recipe = await recipe_service.get_recipe_with_details(int(recipe_id))
    if not recipe:
        return False

    user_id = message.from_user.id if message.from_user else None
    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        await answer_video_and_track(message, redis, video_url, user_id=user_id)
    await answer_and_track(
        message,
        redis,
        build_existing_recipe_text(recipe),
        user_id=user_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=add_recipe_keyboard(int(recipe_id)),
    )
    return True


async def _show_start_menu(
    target_message: Message,
    tg_user: User,
    *,
    bot: Bot,
    redis: Redis,
    user_service: UserService,
) -> None:
    """Очищает прошлые сообщения и показывает стартовое меню."""
    count = await user_service.ensure_user_exists_and_count(
        UserCreate(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
    )
    await RecipeActionCacheRepository.delete_all(redis, tg_user.id)

    new_user = count == 0
    text = START_TEXT_NEW_USER.format(user=tg_user) if new_user else START_TEXT_USER

    await delete_tracked_messages(bot, redis, user_id=tg_user.id, chat_id=target_message.chat.id)
    await send_and_track(
        bot,
        redis,
        chat_id=target_message.chat.id,
        text=text,
        user_id=tg_user.id,
        reply_markup=start_keyboard(new_user),
        parse_mode=ParseMode.HTML,
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    user: User,
    bot: Bot,
    redis: Redis,
    user_service: UserService,
    recipe_service: RecipeService,
) -> None:
    """/start — стартовое меню, в т.ч. deep-link шаринга рецептов."""
    await state.clear()

    token = _parse_shared_token(command.args)
    if token and await handle_shared_start(message, recipe_service, redis, token):
        return

    await _show_start_menu(message, user, bot=bot, redis=redis, user_service=user_service)


@router.callback_query(NavCB.filter(F.action == "start"))
async def cb_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    bot: Bot,
    redis: Redis,
    user_service: UserService,
) -> None:
    """Кнопка «На главную» — возврат в стартовое меню."""
    await callback.answer()
    await state.clear()
    if not isinstance(callback.message, Message):
        return
    await _show_start_menu(callback.message, user, bot=bot, redis=redis, user_service=user_service)


@router.message(Command("help"))
async def cmd_help(message: Message, redis: Redis) -> None:
    """/help — корневой раздел справки."""
    await answer_and_track(
        message,
        redis,
        HELP_TEXT,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=help_keyboard(None),
    )


@router.callback_query(HelpCB.filter())
async def cb_help(callback: CallbackQuery, callback_data: HelpCB) -> None:
    """Инлайн-кнопка «Помощь» и разделы справки."""
    await callback.answer()
    topic = callback_data.topic
    if topic in HELP_TOPICS:
        text, keyboard = HELP_TOPICS[topic], help_keyboard(topic)
    else:
        text, keyboard = HELP_TEXT, help_keyboard(None)

    if isinstance(callback.message, Message):
        await safe_edit(
            callback.message,
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
