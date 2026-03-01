import logging
from contextlib import suppress
from html import escape

from redis.asyncio import Redis
from telegram import CallbackQuery, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest

from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import (
    build_recipes_list_keyboard,
    category_keyboard,
    choice_recipe_keyboard,
    home_keyboard,
    random_recipe_keyboard,
    recipe_edit_keyboard,
)
from bot.app.services.category_service import CategoryService
from bot.app.services.parse_callback import (
    parse_category_mode,
    parse_category_mode_id,
    parse_mode,
)
from bot.app.services.recipe_service import RecipeService
from bot.app.utils.context_helpers import get_db_and_redis
from bot.app.utils.message_utils import random_recipe
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.db.repository import RecipeRepository, VideoRepository
from packages.redis.repository import (
    RecipeActionCacheRepository,
    RecipeMessageCacheRepository,
)

# Включаем логирование
logger = logging.getLogger(__name__)


async def _safe_edit_message(
    cq: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
) -> None:
    """Безопасно редактирует сообщение и отдельно обрабатывает 'message is not modified'."""
    try:
        await cq.edit_message_text(
            text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            with suppress(BadRequest):
                await cq.edit_message_reply_markup(reply_markup=reply_markup)
        else:
            raise


async def _delete_previous_random_video(context: PTBContext, redis: Redis, user_id: int, chat_id: int) -> None:
    """Удаляет предыдущее видео случайного рецепта как минимальный message_id из кеша."""
    data = await RecipeMessageCacheRepository.get_user_message_ids(redis, user_id)
    if not data:
        return
    cached_chat_id = data.get("chat_id")
    message_ids = data.get("message_ids")
    if not isinstance(cached_chat_id, int) or cached_chat_id != int(chat_id):
        return
    if not isinstance(message_ids, list):
        return
    valid_ids = [mid for mid in message_ids if isinstance(mid, int)]
    if len(valid_ids) <= 1:
        return
    previous_video_id = min(valid_ids)
    with suppress(BadRequest):
        await context.bot.delete_message(chat_id=chat_id, message_id=previous_video_id)


async def upload_recipe(update: Update, context: PTBContext) -> None:
    """Обработчик команды /upload_recipe."""
    cq = update.callback_query
    if cq:
        await cq.answer()
        if cq.message:
            await cq.edit_message_text(
                "Пожалуйста, отправьте ссылку на видео с рецептом.",
                reply_markup=home_keyboard(),
                parse_mode=ParseMode.HTML,
            )


async def recipes_menu(update: Update, context: PTBContext) -> None:
    """
    Обработчик нажатия кнопки 'Рецепты'.
    Entry-point: r"^recipes_(?:show|random|edit)$"
    """
    cq = update.callback_query
    if not cq:
        return
    logger.debug("⏩⏩ Получен колбэк: %s", cq)
    await cq.answer()

    user_id = cq.from_user.id
    db, redis = get_db_and_redis(context)
    service = CategoryService(db, redis)
    categories = await service.get_user_categories_cached(user_id)

    mode = parse_mode(cq.data or "")
    if not mode:
        mode = RecipeMode.SHOW
    logger.debug("⏩ Получен колбэк: %s", mode)
    if mode is RecipeMode.RANDOM and cq.message and update.effective_chat:
        await _delete_previous_random_video(
            context=context,
            redis=redis,
            user_id=user_id,
            chat_id=update.effective_chat.id,
        )
        await RecipeMessageCacheRepository.set_user_message_ids(
            redis,
            user_id,
            update.effective_chat.id,
            [cq.message.message_id],
        )
    if mode is RecipeMode.RANDOM:
        text = "🔖 Выберите раздел со случайным блюдом:"
    elif mode is RecipeMode.EDIT:
        text = "🔖 Выберите раздел с блюдом для редактирования:"
    else:
        text = "🔖 Выберите раздел:"

    markup = category_keyboard(categories, mode)

    if cq.message:
        await _safe_edit_message(
            cq,
            text,
            markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def recipes_from_category(update: Update, context: PTBContext) -> None:
    """
    Обработчик выбора категории рецептов.
    Entry-point: r"^([a-z0-9][a-z0-9_-]*)(?:_(show|random|edit))?$"
    """
    cq = update.callback_query
    if not cq or not cq.data:
        logger.error("Нет callback_query или данных в recipes_from_category")
        return
    await cq.answer()

    parsed = parse_category_mode(cq.data)
    if parsed is None:
        logger.error("Некорректный формат callback_query: %s", cq.data)
        return
    category_slug, mode = parsed
    logger.debug("⏩⏩ category_slug = %s, mode = %s", category_slug, mode)

    user_id = cq.from_user.id
    db, redis = get_db_and_redis(context)
    if mode is RecipeMode.RANDOM:
        await _handle_random_from_category(update, context, cq, db, redis, user_id, category_slug)
        return

    await _handle_show_or_edit_from_category(cq, user_id, db, redis, category_slug, mode)


async def _handle_random_from_category(
    update: Update,
    context: PTBContext,
    cq,
    db: Database,
    redis: Redis,
    user_id: int,
    category_slug: str,
) -> None:
    """Сценарий выдачи случайного рецепта из категории."""
    video_url, text = await random_recipe(db, redis, user_id, category_slug)
    random_markup = random_recipe_keyboard(category_slug)

    if not cq.message or not update.effective_chat:
        return

    await _delete_previous_random_video(
        context=context,
        redis=redis,
        user_id=user_id,
        chat_id=update.effective_chat.id,
    )
    with suppress(BadRequest):
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=cq.message.message_id,
        )
    if not text:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="👉 🍽 Здесь появится ваш рецепт, когда вы что-нибудь сохраните.",
            reply_markup=random_markup,
        )
        return
    # показываем видео и текст отдельными сообщениями
    if update.effective_message:
        message_ids: list[int] = []
        if video_url:
            video_msg = await update.effective_message.reply_video(video_url)
            message_ids.append(video_msg.message_id)
        text_msg = await update.effective_message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=random_markup,
        )
        message_ids.append(text_msg.message_id)
        if message_ids and update.effective_chat:
            await RecipeMessageCacheRepository.set_user_message_ids(
                redis,
                cq.from_user.id,
                update.effective_chat.id,
                sorted(message_ids),
            )


async def _handle_show_or_edit_from_category(
    cq: CallbackQuery,
    user_id: int,
    db: Database,
    redis: Redis,
    category_slug: str,
    mode: RecipeMode,
) -> None:
    """Сценарий показа/редактирования списка рецептов в категории."""
    pairs: list[dict[str, str | int]] = []
    service = CategoryService(db, redis)
    category_id, category_name = await service.get_id_and_name_by_slug_cached(category_slug)
    logger.debug("📼 category_id = %s", category_id)
    service_recipe = RecipeService(db, redis)
    if category_id:
        pairs = await service_recipe.get_all_recipes_ids_and_titles(user_id, category_id)
        logger.debug("📼 pairs = %s", pairs)

    if not pairs:
        if cq.message:
            await _safe_edit_message(
                cq,
                f"У вас нет рецептов в категории «{category_name}».",
                home_keyboard(),
            )
        return

    # сохраняем состояние в Redis
    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(pairs) + recipes_per_page - 1) // recipes_per_page
    state = {
        "recipes_page": 0,
        "recipes_total_pages": recipes_total_pages,
        "category_name": category_name,
        "category_slug": category_slug,
        "category_id": category_id,
        "mode": mode.value,
    }
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state)

    # рисуем первую страницу
    markup = build_recipes_list_keyboard(
        pairs,
        page=0,
        per_page=recipes_per_page,
        category_slug=category_slug,
        mode=mode,
    )
    await _safe_edit_message(
        cq,
        f"Выберите рецепт из категории «{category_name}»:",
        markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def recipe_choice(update: Update, context: PTBContext) -> None:
    """
    Обработчик выбора рецепта.
    Entry-point: r'^([a-z0-9][a-z0-9_-]*)_(show|random|edit)_(\\d+)$'
    """
    cq = update.callback_query
    if not cq:
        return

    await cq.answer()

    data = cq.data or ""
    parsed = parse_category_mode_id(data)
    if parsed is None:
        logger.error("Некорректный формат callback_query в recipe_choice: %s", data)
        return
    category_slug, mode_str, recipe_id = parsed
    logger.debug("🗑 %s - category_slug", category_slug)
    if cq.message and update.effective_chat:
        with suppress(BadRequest):
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=cq.message.message_id,
            )
    db, redis = get_db_and_redis(context)
    state = await RecipeActionCacheRepository.get(redis, cq.from_user.id, "recipes_state") or {}
    page = int(state.get("recipes_page", 0))
    if mode_str == RecipeMode.EDIT.value:
        # Редактирование рецепта
        keyboard = recipe_edit_keyboard(recipe_id, page, category_slug, mode_str)
    else:
        keyboard = choice_recipe_keyboard(recipe_id, page, category_slug, mode_str)

    async with db.session() as session:
        recipe = await RecipeRepository.get_by_id(session, recipe_id)
        if not recipe:
            if update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Рецепт не найден.",
                    reply_markup=home_keyboard(),
                )
            return
        video_url = await VideoRepository.get_video_url(session, int(recipe.id))
        if not video_url:
            video_url = None
        await RecipeRepository.update_last_used_at(session, int(recipe.id))
        await session.commit()
        safe_title = escape(recipe.title or "")
        safe_description = escape(recipe.description or "")
        ingredients_text = "\n".join(f"- {escape(ingredient.name or '')}" for ingredient in recipe.ingredients)
        text = (
            f"🍽 <b>Название рецепта:</b> {safe_title}\n\n"
            f"📝 <b>Рецепт:</b>\n{safe_description}\n\n"
            f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
        )
        message_ids: list[int] = []
        if video_url and update.effective_message:
            video_msg = await update.effective_message.reply_video(video_url)
            message_ids.append(video_msg.message_id)

        if update.effective_message:
            text_msg = await update.effective_message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
            message_ids.append(text_msg.message_id)

        if message_ids and update.effective_chat:
            await RecipeMessageCacheRepository.append_user_message_ids(
                redis,
                cq.from_user.id,
                update.effective_chat.id,
                message_ids,
            )
