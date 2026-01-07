from telegram import Update

from bot.app.core.types import AppState, PTBContext
from bot.app.handlers.user import START_TEXT_NEW_USER
from bot.app.keyboards.inlines import (
    category_keyboard,
    home_keyboard,
    start_keyboard,
)
from bot.app.services.category_service import CategoryService
from bot.app.services.user_service import UserService
from bot.app.utils.context_helpers import get_db
from packages.db.repository import RecipeRepository, RecipeUserRepository
from packages.redis.repository import CategoryCacheRepository, RecipeCacheRepository


async def add_existing_recipe(update: Update, context: PTBContext) -> None:
    """Хэндлер для начала процесса добавления существующего рецепта пользователю."""
    cq = update.callback_query
    if not cq or not cq.data:
        return
    await cq.answer()
    try:
        recipe_id = int(cq.data.split(":", 1)[1])
    except (ValueError, TypeError):
        return
    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        return

    db = get_db(context)
    app_state = context.bot_data.get("state")
    if not isinstance(app_state, AppState) or app_state.redis is None:
        await cq.edit_message_text("Redis недоступен, попробуйте позже.", reply_markup=home_keyboard())
        return

    service = CategoryService(db, app_state.redis)
    categories = await service.get_all_category()
    await cq.edit_message_text(
        "Выберите категорию для добавления рецепта:",
        reply_markup=category_keyboard(
            categories,
            callback_builder=lambda slug: f"add_recipe:{recipe_id}:{slug}",
        ),
    )


async def add_existing_recipe_choose_category(update: Update, context: PTBContext) -> None:
    """Хэндлер для выбора категории при добавлении существующего рецепта пользователю."""
    cq = update.callback_query
    if not cq or not cq.data:
        return
    await cq.answer()
    try:
        _, recipe_id_str, slug = cq.data.split(":", 2)
        recipe_id = int(recipe_id_str)
    except (ValueError, TypeError):
        return

    user_id = cq.from_user.id if cq.from_user else None
    if not user_id:
        return

    db = get_db(context)
    app_state = context.bot_data.get("state")
    if not isinstance(app_state, AppState) or app_state.redis is None:
        await cq.edit_message_text("Redis недоступен, попробуйте позже.", reply_markup=home_keyboard())
        return

    category_service = CategoryService(db, app_state.redis)
    category_id, _ = await category_service.get_id_and_name_by_slug_cached(slug)

    message_text = "✅ Рецепт успешно сохранён."
    async with db.session() as session:
        if await RecipeUserRepository.is_linked(session, recipe_id, user_id):
            message_text = "ℹ️ Рецепт уже есть у вас, обновили категорию."
            await RecipeRepository.update_category(session, recipe_id, user_id, category_id)
        else:
            await RecipeUserRepository.link_user(session, recipe_id, user_id, category_id)
        await session.commit()

    await CategoryCacheRepository.invalidate_user_categories(app_state.redis, user_id)
    await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(app_state.redis, user_id, category_id)

    await cq.edit_message_text(message_text, reply_markup=home_keyboard())

    user_service = UserService(db, app_state.redis)
    recipes_count = await user_service.ensure_user_exists_and_count(cq.from_user)
    if recipes_count <= 1:
        tg_user = update.effective_user
        if tg_user and update.effective_message:
            text = START_TEXT_NEW_USER.format(user=tg_user)
            await update.effective_message.reply_text(
                text,
                reply_markup=start_keyboard(new_user=True),
                parse_mode="HTML",
            )
