import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.src.bot_ui.messages import MessageService
from bot.src.interactions.recipe_browse import (
    show_random_recipe_from_category,
    show_recipe_card,
)
from bot.src.keyboards.callback_data import BookCatCB, BookCB, CatCB, ChoiceCB, MenuCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import (
    categories_book_keyboard,
    categories_menu_keyboard,
    recipes_list_keyboard,
)
from bot.src.recipe_flow.book_slug import build_book_slug
from bot.src.recipe_flow.list_state import RecipesStateData
from bot.src.recipe_flow.modes import RecipeMode
from packages.common_settings.settings import settings
from packages.services.category_service import CategoryService
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="browse")


@router.callback_query(MenuCB.filter())
async def recipes_menu(
    callback: CallbackQuery,
    callback_data: MenuCB,
    user: User,
    category_service: CategoryService,
    bot: Bot,
    message_service: MessageService,
) -> None:
    """Меню «Мои рецепты» / «Случайные рецепты» — список категорий пользователя."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    categories = await category_service.get_user_categories_cached(user.id)

    try:
        mode = RecipeMode(callback_data.mode)
    except ValueError:
        mode = RecipeMode.SHOW

    if mode is RecipeMode.RANDOM:
        chat_id = callback.message.chat.id
        await message_service.delete_previous_random_video(bot, chat_id=chat_id)
        await message_service.remember_tracked_messages(
            chat_id=chat_id,
            message_ids=[callback.message.message_id],
        )

    text = "🔖 Выберите раздел со случайным блюдом:" if mode is RecipeMode.RANDOM else "🔖 Выберите раздел:"
    await message_service.safe_edit(
        callback.message,
        text,
        reply_markup=categories_menu_keyboard(categories, mode),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.callback_query(BookCB.filter())
async def recipes_book_menu(
    callback: CallbackQuery,
    category_service: CategoryService,
    message_service: MessageService,
) -> None:
    """Кнопка «Книга рецептов» — список категорий каталога."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return

    categories = await category_service.get_all_category()
    if not categories:
        await message_service.safe_edit(
            callback.message,
            "Книга рецептов пока пуста.",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    await message_service.safe_edit(
        callback.message,
        "📚 Выберите раздел книги рецептов:",
        reply_markup=categories_book_keyboard(categories),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.callback_query(BookCatCB.filter())
async def recipes_book_from_category(
    callback: CallbackQuery,
    callback_data: BookCatCB,
    user: User,
    state: FSMContext,
    category_service: CategoryService,
    recipe_service: RecipeService,
    message_service: MessageService,
) -> None:
    """Выбор категории книги рецептов."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    category_slug = callback_data.slug

    try:
        category_id, category_name = await category_service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        logger.warning("Категория книги рецептов не найдена: slug=%s", category_slug)
        await message_service.safe_edit(
            callback.message,
            "Выбранная категория не найдена. Откройте «Книгу рецептов» и выберите раздел заново.",
            reply_markup=home_keyboard(),
        )
        return

    pairs = await recipe_service.get_public_recipes_ids_and_titles(category_id, exclude_user_id=user.id)
    if not pairs:
        await message_service.safe_edit(
            callback.message,
            f"В категории «{category_name}» пока нет рецептов с видео.",
            reply_markup=home_keyboard(),
        )
        return

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(pairs) + recipes_per_page - 1) // recipes_per_page
    recipes_state = RecipesStateData.for_book(
        category_name=category_name,
        category_slug=category_slug,
        recipes_total_pages=recipes_total_pages,
        search_items=pairs,
    )
    await state.update_data(recipes_state=recipes_state.to_dict())

    markup = recipes_list_keyboard(
        pairs,
        page=0,
        per_page=recipes_per_page,
        category_slug=build_book_slug(category_slug),
        mode=RecipeMode.SHOW,
        categories_callback=BookCB(),
    )
    await message_service.safe_edit(
        callback.message,
        f"📚 Рецепты категории «{category_name}»:",
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.callback_query(CatCB.filter(F.mode.in_({"show", "random"})))
async def recipes_from_category(
    callback: CallbackQuery,
    callback_data: CatCB,
    user: User,
    state: FSMContext,
    category_service: CategoryService,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
) -> None:
    """Выбор категории пользователя: показать список или случайный рецепт."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    category_slug = callback_data.slug
    mode = RecipeMode(callback_data.mode)

    if mode is RecipeMode.RANDOM:
        await show_random_recipe_from_category(
            callback.message,
            category_service,
            recipe_service,
            bot,
            message_service,
            user.id,
            category_slug,
        )
    else:
        await _handle_show_from_category(
            callback.message,
            state,
            category_service,
            recipe_service,
            message_service,
            user.id,
            category_slug,
            mode,
        )


async def _handle_show_from_category(
    message: Message,
    state: FSMContext,
    category_service: CategoryService,
    recipe_service: RecipeService,
    message_service: MessageService,
    user_id: int,
    category_slug: str,
    mode: RecipeMode,
) -> None:
    """Сценарий показа списка рецептов в категории."""
    try:
        category_id, category_name = await category_service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        logger.warning("Категория пользователя не найдена: slug=%s user_id=%s", category_slug, user_id)
        await message_service.safe_edit(
            message, "Выбранная категория не найдена. Откройте раздел заново.", reply_markup=home_keyboard()
        )
        return

    pairs = await recipe_service.get_all_by_user_and_category(user_id, category_id) if category_id else []
    if not pairs:
        await message_service.safe_edit(
            message, f"У вас нет рецептов в категории «{category_name}».", reply_markup=home_keyboard()
        )
        return

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(pairs) + recipes_per_page - 1) // recipes_per_page
    recipes_state = RecipesStateData.for_category(
        category_name=category_name,
        category_slug=category_slug,
        category_id=category_id,
        mode=mode,
        recipes_total_pages=recipes_total_pages,
    )
    await state.update_data(recipes_state=recipes_state.to_dict())

    markup = recipes_list_keyboard(
        pairs,
        page=0,
        per_page=recipes_per_page,
        category_slug=category_slug,
        mode=mode,
    )
    await message_service.safe_edit(
        message,
        f"Выберите рецепт из категории «{category_name}»:",
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.callback_query(ChoiceCB.filter())
async def recipe_choice(
    callback: CallbackQuery,
    callback_data: ChoiceCB,
    state: FSMContext,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
) -> None:
    """Открытие карточки выбранного рецепта."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return

    await show_recipe_card(
        callback.message,
        bot=bot,
        message_service=message_service,
        state=state,
        recipe_service=recipe_service,
        recipe_id=callback_data.recipe_id,
        category_slug=callback_data.category,
        mode=callback_data.mode,
    )
