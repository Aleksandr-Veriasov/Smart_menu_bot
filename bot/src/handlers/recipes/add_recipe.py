import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from bot.src.handlers.user import START_TEXT_NEW_USER
from bot.src.keyboards.callback_data import AddCatCB, RecipeCB
from bot.src.keyboards.menu import home_keyboard, start_keyboard
from bot.src.keyboards.recipe import categories_add_keyboard
from bot.src.utils.messaging import answer_and_track, safe_edit
from packages.db.schemas import UserCreate
from packages.services.category_service import CategoryService
from packages.services.recipe_service import RecipeService
from packages.services.user_service import UserService

logger = logging.getLogger(__name__)

router = Router(name="add_recipe")


@router.callback_query(RecipeCB.filter(F.action == "add"))
async def add_existing_recipe(
    callback: CallbackQuery,
    callback_data: RecipeCB,
    category_service: CategoryService,
) -> None:
    """Начало добавления существующего рецепта: выбор категории."""
    await callback.answer()
    categories = await category_service.get_all_category()
    await safe_edit(
        callback.message,
        "Выберите категорию для добавления рецепта:",
        reply_markup=categories_add_keyboard(categories, callback_data.recipe_id),
    )


@router.callback_query(AddCatCB.filter())
async def add_existing_recipe_choose_category(
    callback: CallbackQuery,
    callback_data: AddCatCB,
    category_service: CategoryService,
    recipe_service: RecipeService,
    user_service: UserService,
    redis: Redis,
) -> None:
    """Привязка существующего рецепта к выбранной категории пользователя."""
    await callback.answer()
    if not callback.from_user:
        return
    recipe_id, slug = callback_data.recipe_id, callback_data.slug
    user = callback.from_user

    try:
        category_id, _ = await category_service.get_id_and_name_by_slug_cached(slug)
    except ValueError:
        await safe_edit(
            callback.message,
            "Категория не найдена. Попробуйте выбрать её заново.",
            reply_markup=home_keyboard(),
        )
        logger.error("Категория с slug '%s' не найдена для пользователя %s", slug, user.id)
        return

    created = await recipe_service.link_recipe_to_user(recipe_id, user.id, category_id)
    message_text = "✅ Рецепт успешно сохранён." if created else "ℹ️ Рецепт уже есть у вас, обновили категорию."
    await safe_edit(callback.message, message_text, reply_markup=home_keyboard())

    recipes_count = await user_service.ensure_user_exists_and_count(
        UserCreate(id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name)
    )
    # Если это первый рецепт пользователя — покажем стартовое сообщение новичка.
    if recipes_count <= 1 and isinstance(callback.message, Message):
        await answer_and_track(
            callback.message,
            redis,
            START_TEXT_NEW_USER.format(user=user),
            user_id=user.id,
            reply_markup=start_keyboard(new_user=True),
            parse_mode=ParseMode.HTML,
        )
