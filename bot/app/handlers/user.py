import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ConversationHandler

from bot.app.core.types import PTBContext
from bot.app.handlers.recipes.share_link import handle_shared_start
from bot.app.keyboards.inlines import help_keyboard, start_keyboard
from bot.app.services.user_service import UserService
from bot.app.utils.context_helpers import get_db_and_redis
from bot.app.utils.message_cache import (
    append_message_id_to_cache,
    collapse_user_messages,
)
from packages.redis.repository import RecipeActionCacheRepository

logger = logging.getLogger(__name__)


START_TEXT_NEW_USER = (
    "Привет {user.first_name}! 👋 Я — бот, который помогает вам удобно "
    "сохранять <b>рецепты</b>, которые вам понравились в <b>ТикТоке</b>, "
    "<b>Инстаграме</b> или <b>Пинтересте</b>. Вот что я могу сделать для вас:\n\n"
    "✨ <b>Сохранить рецепты</b> и ингредиенты из видео\n"
    "🔍 <b>Искать рецепты</b> по категориям\n"
    "🎲 <b>Предложить случайное блюдо</b> из ваших сохранёнок\n"
    "📩 <b>Чтобы загрузить рецепт</b> — просто пришлите мне ссылку "
    "на Reels, TikTok или Pinterest."
    # "<b>Выберите действие</b> 👇"
)

START_TEXT_USER = (
    "Выберете то, что хотите сделать:\n\n"
    "• <b>Рецепты</b> — просмотреть сохранённые рецепты\n"
    "• <b>Случайное блюдо</b> — получить случайный рецепт\n"
    # "• <b>Загрузить рецепт</b> — отправить ссылку на видео с рецептом\n"
    "• <b>Поиск рецептов</b> - поиск по названию или ингредиенту\n"
    "• <b>Редактировать рецепт</b> — изменить категорию или удалить рецепт\n\n"
    "Чтобы загрузить новый рецепт, просто отправьте мне ссылку на видео из TikTok, Reels или Pinterest."
)

HELP_TEXT = (
    "🤖 <b>SmartMenuBot</b> — ваш помощник для сохранения рецептов из "
    "TikTok и Reels!\n\n"
    "<b>📌 Что я умею:</b>\n"
    "• Сохранять рецепты и ингредиенты из видео\n"
    "• Сортировать рецепты по категориям (завтрак, обед и салат)\n"
    "• Предлагать случайный рецепт из сохранённых\n"
    "• Позволять редактировать название и удалять рецепты\n\n"
    "<b>🛠 Как пользоваться:</b>\n"
    "1️⃣ Отправьте ссылку на видео из TikTok, Instagram Reels или Pinterest\n"
    "   — я обработаю его, распознаю речь и сохраню рецепт\n"
    "2️⃣ Выбери категорию, куда сохранить рецепт:\n"
    "3️⃣ Вы можете:\n"
    "   • 📂 Просмотреть рецепты по категориям\n"
    "   • ✏️ Редактировать категорию рецептов\n"
    "   • ❌ Удалить рецепт\n"
    "   • 🎲 Получить случайный рецепт\n"
    "   • 📤 Поделиться рецептов с другом\n\n"
    "<b>💬 Команды:</b>\n"
    "/start — Перезапустить бота\n"
    "/help — Показать это сообщение\n\n"
    "<i>Приятного приготовления! 🍽</i>"
)


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

    if update.callback_query:
        await update.callback_query.answer()

    if update.effective_chat and await collapse_user_messages(
        context,
        redis,
        tg_user.id,
        update.effective_chat.id,
        text,
        keyboard,
    ):
        return ConversationHandler.END

    cq = update.callback_query
    if cq:
        await cq.answer()  # убираем «часики»
        # если есть исходное сообщение — отвечаем рядом
        if cq.message:
            try:
                await cq.edit_message_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except BadRequest as exc:
                # Telegram returns this when user presses the same button again
                # and the message content/markup is identical.
                if "Message is not modified" not in str(exc):
                    raise
        return ConversationHandler.END
    # Если это не callback_query, то обычное сообщение
    msg = update.effective_message
    if msg:
        reply = await msg.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await append_message_id_to_cache(update, context, reply.message_id)
    return ConversationHandler.END


async def user_help(update: Update, context: PTBContext) -> None:
    """Обработчик команды /help и нажатия инлайн-кнопки «Помощь»."""
    # 1) Нажатие инлайн-кнопки «Помощь»
    if update.callback_query:
        cq = update.callback_query
        await cq.answer()  # убираем «часики»
        # если есть исходное сообщение — отвечаем рядом
        if cq.message:
            try:
                await cq.edit_message_text(
                    HELP_TEXT,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=help_keyboard(),
                )
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise
        return

    # 2) Обычная команда /help как сообщение
    msg = update.effective_message
    if msg:
        reply = await msg.reply_text(
            HELP_TEXT,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=help_keyboard(),
        )
        await append_message_id_to_cache(update, context, reply.message_id)
