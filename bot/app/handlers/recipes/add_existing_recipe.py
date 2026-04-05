import logging

from telegram import Update

from bot.app.core.types import PTBContext
from bot.app.handlers.user import START_TEXT_NEW_USER
from bot.app.keyboards.callbacks import RecipeCallbacks
from bot.app.keyboards.inlines import (
    category_keyboard,
    home_keyboard,
    start_keyboard,
)
from bot.app.services.category_service import CategoryService
from bot.app.services.user_service import UserService
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db_and_redis
from bot.app.utils.message_cache import reply_text_and_cache
from bot.app.utils.message_utils import safe_edit_message
from packages.db.repository import RecipeUserRepository
from packages.redis.repository import CategoryCacheRepository, RecipeCacheRepository

logger = logging.getLogger(__name__)


async def maybe_send_new_user_start_message(update: Update, context: PTBContext, recipes_count: int) -> None:
    """Показывает стартовое сообщение, если это первый рецепт пользователя."""
    if recipes_count > 1:
        return
    message = update.effective_message
    tg_user = update.effective_user
    if not message or not tg_user:
        return
    await reply_text_and_cache(
        message,
        context,
        START_TEXT_NEW_USER.format(user=tg_user),
        user_id=tg_user.id,
        reply_markup=start_keyboard(new_user=True),
        parse_mode="HTML",
    )


async def add_existing_recipe(update: Update, context: PTBContext) -> None:
    """
    Хэндлер для начала процесса добавления существующего рецепта пользователю.
    Entry-point: callback `recipe:add:<recipe_id>`.
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq:
        return
    recipe_id = RecipeCallbacks.parse_recipe_add(cq.data)
    if recipe_id is None:
        return

    db, redis = get_db_and_redis(context)
    category_service = CategoryService(db, redis)
    categories = await category_service.get_all_category()
    await safe_edit_message(
        cq,
        "Выберите категорию для добавления рецепта:",
        reply_markup=category_keyboard(
            categories,
            callback_builder=lambda slug: RecipeCallbacks.build_recipe_add_category(recipe_id, slug),
        ),
    )


async def add_existing_recipe_choose_category(update: Update, context: PTBContext) -> None:
    """
    Хэндлер для выбора категории при добавлении существующего рецепта пользователю.
    Entry-point: callback `recipe:addcat:<recipe_id>:<category_slug>`.
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq:
        return
    parsed = RecipeCallbacks.parse_recipe_add_category(cq.data)
    if parsed is None:
        return
    recipe_id, slug = parsed

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        return

    db, redis = get_db_and_redis(context)
    category_service = CategoryService(db, redis)
    try:
        category_id, _ = await category_service.get_id_and_name_by_slug_cached(slug)
    except ValueError:
        await safe_edit_message(
            cq,
            "Категория не найдена. Попробуйте выбрать её заново.",
            reply_markup=home_keyboard(),
        )
        logger.error("Категория с slug '%s' не найдена для пользователя %s", slug, user_id)
        return

    async with db.session() as session:
        created = await RecipeUserRepository.upsert_user_link(session, recipe_id, user_id, category_id)

    message_text = "✅ Рецепт успешно сохранён." if created else "ℹ️ Рецепт уже есть у вас, обновили категорию."

    await CategoryCacheRepository.invalidate_user_categories(redis, user_id)
    await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(redis, user_id, category_id)

    await safe_edit_message(cq, message_text, reply_markup=home_keyboard())

    user_service = UserService(db, redis)
    recipes_count = await user_service.ensure_user_exists_and_count(cq.from_user)
    await maybe_send_new_user_start_message(update, context, recipes_count)
