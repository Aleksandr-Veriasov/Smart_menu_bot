import logging

from telegram import Update
from telegram.ext import ConversationHandler

from bot.app.core.types import PTBContext
from bot.app.handlers.recipes.share_link import handle_shared_start
from bot.app.keyboards.inlines import help_keyboard, start_keyboard
from bot.app.services.user_service import UserService
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db_and_redis
from bot.app.utils.message_cache import (
    delete_all_user_messages,
    reply_text_and_cache,
    send_message_and_cache,
)
from bot.app.utils.message_utils import safe_edit_message
from packages.redis.repository import RecipeActionCacheRepository

logger = logging.getLogger(__name__)


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


def help_payload(callback_data: str | None) -> tuple[str, str | None]:
    if callback_data and callback_data.startswith("help:"):
        topic = callback_data.split(":", 1)[1].strip().lower()
        return HELP_TOPICS.get(topic, HELP_TEXT), topic if topic in HELP_TOPICS else None
    return HELP_TEXT, None


async def user_start(update: Update, context: PTBContext) -> int:
    """Обработчик команды /start"""
    tg_user = update.effective_user
    if not tg_user:
        logger.error("update.effective_user отсутствует в функции start")
        return ConversationHandler.END

    args = context.args or []
    if args and args[0].startswith("share_"):
        token = args[0].removeprefix("share_")
        if await handle_shared_start(update, context, token):
            return ConversationHandler.END

    db, redis = get_db_and_redis(context)
    service = UserService(db, redis)
    count = await service.ensure_user_exists_and_count(tg_user)

    await RecipeActionCacheRepository.delete_all(redis, tg_user.id)

    new_user = True if count == 0 else False
    text_new_user = START_TEXT_NEW_USER.format(user=tg_user)
    text = text_new_user if new_user else START_TEXT_USER
    keyboard = start_keyboard(new_user)

    if update.effective_chat:
        await delete_all_user_messages(context, redis, tg_user.id, update.effective_chat.id)
        await send_message_and_cache(
            update,
            context,
            update.effective_chat.id,
            text,
            user_id=tg_user.id,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return ConversationHandler.END

    msg = update.effective_message
    if msg:
        await reply_text_and_cache(msg, context, text, user_id=tg_user.id, reply_markup=keyboard, parse_mode="HTML")
    return ConversationHandler.END


async def user_help(update: Update, context: PTBContext) -> None:
    """Обработчик команды /help и нажатия инлайн-кнопки «Помощь»."""
    cq = await get_answered_callback_query(update)
    if cq:
        text, topic = help_payload(cq.data)
        if cq.message:
            await safe_edit_message(
                cq,
                text,
                help_keyboard(topic),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        return

    msg = update.effective_message
    if msg:
        await reply_text_and_cache(
            msg,
            context,
            HELP_TEXT,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=help_keyboard(None),
        )
