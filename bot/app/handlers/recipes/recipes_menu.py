import logging

from redis.asyncio import Redis
from telegram import CallbackQuery, Update
from telegram.constants import ParseMode

from bot.app.core.data_models import RecipesStateData
from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import (
    build_recipes_list_keyboard,
    category_keyboard,
    choice_recipe_keyboard,
    home_keyboard,
    random_recipe_keyboard,
)
from bot.app.services.category_service import CategoryService
from bot.app.services.parse_callback import (
    parse_category_mode,
    parse_category_mode_id,
    parse_mode,
)
from bot.app.services.recipe_service import RecipeService
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db_and_redis
from bot.app.utils.message_cache import (
    delete_all_user_messages,
    reply_text_and_cache,
    reply_video_and_cache,
    send_message_and_cache,
)
from bot.app.utils.message_random import random_recipe
from bot.app.utils.message_utils import (
    build_existing_recipe_text,
    delete_message_safely,
    delete_previous_random_video,
    safe_edit_message,
)
from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.db.repository import RecipeRepository
from packages.redis.repository import (
    RecipeActionCacheRepository,
    UserMessageIdsCacheRepository,
)

# Включаем логирование
logger = logging.getLogger(__name__)


async def recipes_menu(update: Update, context: PTBContext) -> None:
    """
    Обработчик нажатия кнопки 'Рецепты'.
    Entry-point: r"^recipes_(?:show|random)$"
    """
    cq = await get_answered_callback_query(update)
    if not cq:
        return

    user_id = cq.from_user.id
    db, redis = get_db_and_redis(context)
    service = CategoryService(db, redis)
    categories = await service.get_user_categories_cached(user_id)

    mode = parse_mode(cq.data or "")
    if not mode:
        mode = RecipeMode.SHOW
    if mode is RecipeMode.RANDOM and cq.message and update.effective_chat:
        await delete_previous_random_video(
            context=context,
            redis=redis,
            user_id=user_id,
            chat_id=update.effective_chat.id,
        )
        await UserMessageIdsCacheRepository.set_user_message_ids(
            redis,
            user_id,
            update.effective_chat.id,
            [cq.message.message_id],
        )
    text = "🔖 Выберите раздел со случайным блюдом:" if mode is RecipeMode.RANDOM else "🔖 Выберите раздел:"

    if cq.message:
        await safe_edit_message(
            cq=cq,
            text=text,
            reply_markup=category_keyboard(categories, mode),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def recipes_book_menu(update: Update, context: PTBContext) -> None:
    """
    Обработчик кнопки "Книга рецептов".
    Entry-point: r"^recipes_book$"
    """
    cq = await get_answered_callback_query(update)
    if not cq:
        return

    db, redis = get_db_and_redis(context)
    service = CategoryService(db, redis)
    categories = await service.get_all_category()

    if not categories:
        if cq.message:
            await safe_edit_message(
                cq=cq,
                text="Книга рецептов пока пуста.",
                reply_markup=home_keyboard(),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        return

    if cq.message:
        await safe_edit_message(
            cq=cq,
            text="📚 Выберите раздел книги рецептов:",
            reply_markup=category_keyboard(categories, callback_builder=lambda slug: f"bookcat_{slug}"),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def recipes_book_from_category(update: Update, context: PTBContext) -> None:
    """
    Обработчик выбора категории книги рецептов.
    Entry-point: r"^bookcat_[a-z0-9][a-z0-9_-]*$"
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.data:
        return

    category_slug = cq.data.removeprefix("bookcat_").strip().lower()
    if not category_slug:
        return

    user_id = cq.from_user.id
    db, redis = get_db_and_redis(context)
    service = CategoryService(db, redis)
    try:
        category_id, category_name = await service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        logger.warning("Категория книги рецептов не найдена: slug=%s", category_slug)
        if cq.message:
            await safe_edit_message(
                cq=cq,
                text="Выбранная категория не найдена. Откройте «Книгу рецептов» и выберите раздел заново.",
                reply_markup=home_keyboard(),
            )
        return
    async with db.session() as session:
        pairs = await RecipeRepository.get_public_recipes_ids_and_titles_by_category(
            session,
            category_id,
            exclude_user_id=user_id,
        )

    if not pairs:
        if cq.message:
            await safe_edit_message(
                cq=cq,
                text=f"В категории «{category_name}» пока нет рецептов с видео.",
                reply_markup=home_keyboard(),
            )
        return

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(pairs) + recipes_per_page - 1) // recipes_per_page
    state = RecipesStateData.for_book(
        category_name=category_name,
        category_slug=category_slug,
        recipes_total_pages=recipes_total_pages,
        search_items=pairs,
    )
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state.to_dict())

    markup = build_recipes_list_keyboard(
        pairs,
        page=0,
        per_page=recipes_per_page,
        category_slug=f"book_{category_slug}",
        mode=RecipeMode.SHOW,
        categories_callback="recipes_book",
    )
    if cq.message:
        await safe_edit_message(
            cq=cq,
            text=f"📚 Рецепты категории «{category_name}»:",
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def recipes_from_category(update: Update, context: PTBContext) -> None:
    """
    Обработчик выбора категории рецептов.
    Entry-point: r"^([a-z0-9][a-z0-9_-]*)(?:_(show|random))?$"
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.data:
        return

    parsed = parse_category_mode(cq.data)
    if parsed is None:
        logger.error("Некорректный формат callback_query: %s", cq.data)
        return
    category_slug, mode = parsed
    user_id = cq.from_user.id
    db, redis = get_db_and_redis(context)
    if mode is RecipeMode.RANDOM:
        await handle_random_from_category(update, context, cq, db, redis, user_id, category_slug)
        return

    await handle_show_or_edit_from_category(cq, user_id, db, redis, category_slug, mode)


async def handle_random_from_category(
    update: Update,
    context: PTBContext,
    cq: CallbackQuery,
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

    await delete_all_user_messages(context, redis, user_id, update.effective_chat.id)
    if not text:
        await send_message_and_cache(
            update,
            context,
            update.effective_chat.id,
            text="👉 🍽 Здесь появится ваш рецепт, когда вы что-нибудь сохраните.",
            user_id=user_id,
            reply_markup=random_markup,
        )
        return
    if update.effective_message:
        if video_url:
            await reply_video_and_cache(update.effective_message, context, video_url, user_id=user_id)
        await reply_text_and_cache(
            update.effective_message,
            context,
            text,
            user_id=user_id,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=random_markup,
        )


async def handle_show_or_edit_from_category(
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
    try:
        category_id, category_name = await service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        logger.warning("Категория пользователя не найдена: slug=%s user_id=%s", category_slug, user_id)
        if cq.message:
            await safe_edit_message(
                cq,
                "Выбранная категория не найдена. Откройте раздел заново.",
                home_keyboard(),
            )
        return
    service_recipe = RecipeService(db, redis)
    if category_id:
        pairs = await service_recipe.get_all_recipes_ids_and_titles(user_id, category_id)

    if not pairs:
        if cq.message:
            await safe_edit_message(
                cq,
                f"У вас нет рецептов в категории «{category_name}».",
                home_keyboard(),
            )
        return

    # сохраняем состояние в Redis
    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(pairs) + recipes_per_page - 1) // recipes_per_page
    state = RecipesStateData.for_category(
        category_name=category_name,
        category_slug=category_slug,
        category_id=category_id,
        mode=mode,
        recipes_total_pages=recipes_total_pages,
    )
    await RecipeActionCacheRepository.set(redis, user_id, "recipes_state", state.to_dict())

    # рисуем первую страницу
    markup = build_recipes_list_keyboard(
        pairs,
        page=0,
        per_page=recipes_per_page,
        category_slug=category_slug,
        mode=mode,
    )
    await safe_edit_message(
        cq,
        f"Выберите рецепт из категории «{category_name}»:",
        markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def recipe_choice(update: Update, context: PTBContext) -> None:
    """
    Обработчик выбора рецепта.
    Entry-point: r'^([a-z0-9][a-z0-9_-]*)_(show|random)_(\\d+)$'
    """
    cq = await get_answered_callback_query(update)
    if not cq or not cq.data:
        return

    parsed = parse_category_mode_id(cq.data)
    if parsed is None:
        logger.error("Некорректный формат callback_query в recipe_choice: %s", cq.data)
        return
    category_slug, mode_str, recipe_id = parsed
    await delete_message_safely(cq.message)
    db, redis = get_db_and_redis(context)
    state = RecipesStateData.from_dict(await RecipeActionCacheRepository.get(redis, cq.from_user.id, "recipes_state"))
    page = state.recipes_page
    keyboard = choice_recipe_keyboard(
        recipe_id,
        page,
        category_slug,
        mode_str,
        add_to_self=category_slug.startswith("book_"),
        can_manage=mode_str == RecipeMode.SHOW.value and not category_slug.startswith("book_"),
    )

    async with db.session() as session:
        recipe = await RecipeRepository.get_recipe_with_connections(session, recipe_id)
        if recipe:
            await RecipeRepository.update_last_used_at(session, int(recipe.id))

    if not recipe:
        if update.effective_chat:
            await send_message_and_cache(
                update,
                context,
                update.effective_chat.id,
                text="❌ Рецепт не найден.",
                user_id=cq.from_user.id,
                reply_markup=home_keyboard(),
            )
        return

    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    text = build_existing_recipe_text(recipe)
    if video_url and update.effective_message:
        await reply_video_and_cache(update.effective_message, context, video_url, user_id=cq.from_user.id)

    if update.effective_message:
        await reply_text_and_cache(
            update.effective_message,
            context,
            text,
            user_id=cq.from_user.id,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=keyboard,
        )
