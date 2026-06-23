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


START_TEXT_NEW_USER = (
    "Привет, {user.first_name}! 👋\n\n"
    "Я помогу сохранить рецепт из видео и быстро вернуть его, когда он понадобится.\n\n"
    "<b>Как начать:</b>\n"
    "1️⃣ Отправьте ссылку на видео из TikTok, Reels или Pinterest\n"
    "2️⃣ Подтвердите сохранение рецепта в нужную категорию\n\n"
    "<b>Сейчас вам доступны:</b>\n"
    "• 📚 <b>Книга рецептов</b> — рецепты сообщества\n"
    "• ❓ <b>Помощь</b> — подробное описание всех функций\n\n"
    "После первого сохранения откроются разделы «Мои рецепты», «Поиск» и «Случайное блюдо»."
)

START_TEXT_USER = (
    "Выберите, что хотите сделать:\n\n"
    "• <b>Мои рецепты</b> — ваши сохранённые рецепты по категориям\n"
    "• <b>Книга рецептов</b> — рецепты сообщества\n"
    "• <b>Случайные рецепты</b> — идея для готовки в один клик\n"
    "• <b>Поиск рецептов</b> — поиск по названию и ингредиентам\n"
    "• <b>В карточке рецепта</b> — редактирование и удаление\n\n"
    "Чтобы добавить новый рецепт, отправьте ссылку на видео из TikTok, Reels или Pinterest."
)

HELP_TEXT = (
    "📚 <b>Справка SmartMenuBot</b>\n\n"
    "SmartMenuBot автоматизирует сохранение и управление рецептами из видео.\n\n"
    "Выберите раздел ниже, чтобы получить детальную инструкцию по конкретной функции."
)

HELP_TOPICS: dict[str, str] = {
    "upload": (
        "📥 <b>Загрузка рецепта</b>\n\n"
        "Отправьте ссылку на видео из TikTok, Reels или Pinterest обычным сообщением.\n"
        "Бот обработает видео, извлечёт текст рецепта и соберёт список ингредиентов.\n"
        "После обработки появится карточка предпросмотра и кнопка сохранения.\n"
        "Выберите категорию, и рецепт попадёт в ваш личный список.\n\n"
        "Если распознавание неточное, откройте рецепт и отредактируйте его в карточке."
    ),
    "my_recipes": (
        "📖 <b>Мои рецепты</b>\n\n"
        "Этот раздел показывает только ваши сохранённые рецепты.\n"
        "Сначала выбираете категорию, затем конкретный рецепт из списка.\n"
        "В карточке доступно: видео, описание, ингредиенты, кнопка поделиться.\n"
        "Там же можно редактировать и удалять рецепт.\n\n"
        "Если рецептов много, используйте поиск для быстрого доступа."
    ),
    "book": (
        "📚 <b>Книга рецептов</b>\n\n"
        "Это общая библиотека рецептов от других пользователей.\n"
        "Выберите категорию и откройте понравившийся рецепт.\n"
        "Из карточки можно добавить рецепт к себе в один клик.\n"
        "После добавления он появится в разделе «Мои рецепты».\n\n"
        "Книга полезна, когда хотите быстро пополнить свою базу идеями."
    ),
    "search": (
        "🔍 <b>Поиск рецептов</b>\n\n"
        "Поиск работает только по вашим рецептам.\n"
        "Режим «по названию» подходит, если помните часть заголовка.\n"
        "Режим «по ингредиентам» помогает найти блюда из нужных продуктов.\n"
        "Результаты выводятся списком, откуда можно открыть карточку рецепта.\n\n"
        "В этом же меню можно перейти к сценарию случайного рецепта."
    ),
    "random": (
        "🎲 <b>Случайный рецепт</b>\n\n"
        "Функция выбирает случайный рецепт из выбранной категории.\n"
        "Полезно, когда не хотите долго выбирать, что приготовить.\n"
        "Открывается видео и текст рецепта с ингредиентами.\n"
        "Кнопка «Еще рецепт» сразу показывает следующий вариант.\n\n"
        "Если в категории пусто, бот подскажет, что сначала нужно что-то сохранить."
    ),
    "manage": (
        "✏️ <b>Редактирование и удаление</b>\n\n"
        "Управление находится в карточке вашего рецепта.\n"
        "Кнопка «Редактировать рецепт» открывает форму, где можно поправить данные.\n"
        "Кнопка «Удалить рецепт» удаляет рецепт из вашего списка после подтверждения.\n"
        "Эти действия доступны только для ваших рецептов, не для книги рецептов.\n\n"
        "Если сомневаетесь, сначала откройте редактирование и проверьте содержимое."
    ),
    "share": (
        "📤 <b>Поделиться рецептом</b>\n\n"
        "В карточке рецепта есть кнопка для создания ссылки-приглашения.\n"
        "Откройте ссылку или отправьте другу в любой мессенджер.\n"
        "По этой ссылке рецепт открывается и добавляется к себе в один клик.\n"
        "Это удобно для обмена проверенными рецептами без пересылки скриншотов.\n\n"
        "После добавления получатель сможет редактировать рецепт у себя отдельно."
    ),
}

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
    bot: Bot,
    redis: Redis,
    user_service: UserService,
    recipe_service: RecipeService,
) -> None:
    """/start — стартовое меню, в т.ч. deep-link шаринга рецептов."""
    await state.clear()
    tg_user = message.from_user
    if not tg_user:
        logger.error("message.from_user отсутствует в /start")
        return

    token = _parse_shared_token(command.args)
    if token and await handle_shared_start(message, recipe_service, redis, token):
        return

    await _show_start_menu(message, tg_user, bot=bot, redis=redis, user_service=user_service)


@router.callback_query(NavCB.filter(F.action == "start"))
async def cb_start(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    redis: Redis,
    user_service: UserService,
) -> None:
    """Кнопка «На главную» — возврат в стартовое меню."""
    await callback.answer()
    await state.clear()
    tg_user = callback.from_user
    if not isinstance(callback.message, Message):
        return
    await _show_start_menu(callback.message, tg_user, bot=bot, redis=redis, user_service=user_service)


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
