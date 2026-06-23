import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from bot.src.core.book_slug import build_book_slug, is_book_slug
from bot.src.core.data_models import RecipesStateData
from bot.src.core.recipes_mode import RecipeMode
from bot.src.keyboards.callback_data import BookCatCB, BookCB, CatCB, ChoiceCB, MenuCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import (
    categories_book_keyboard,
    categories_menu_keyboard,
    choice_recipe_keyboard,
    random_recipe_keyboard,
    recipes_list_keyboard,
)
from bot.src.utils.messaging import (
    answer_and_track,
    answer_video_and_track,
    delete_message_safely,
    delete_previous_random_video,
    delete_tracked_messages,
    safe_edit,
    send_and_track,
)
from bot.src.utils.recipe_text import build_existing_recipe_text
from packages.common_settings.settings import settings
from packages.redis.repository import (
    RecipeActionCacheRepository,
    UserMessageIdsCacheRepository,
)
from packages.services.category_service import CategoryService
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="browse")


@router.callback_query(MenuCB.filter())
async def recipes_menu(
    callback: CallbackQuery,
    callback_data: MenuCB,
    category_service: CategoryService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Меню «Мои рецепты» / «Случайные рецепты» — список категорий пользователя."""
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    user_id = callback.from_user.id
    categories = await category_service.get_user_categories_cached(user_id)

    try:
        mode = RecipeMode(callback_data.mode)
    except ValueError:
        mode = RecipeMode.SHOW

    if mode is RecipeMode.RANDOM:
        chat_id = callback.message.chat.id
        await delete_previous_random_video(bot, redis, user_id=user_id, chat_id=chat_id)
        await UserMessageIdsCacheRepository.set_user_message_ids(
            redis,
            user_id=user_id,
            chat_id=chat_id,
            message_ids=[callback.message.message_id],
        )

    text = "🔖 Выберите раздел со случайным блюдом:" if mode is RecipeMode.RANDOM else "🔖 Выберите раздел:"
    await safe_edit(
        callback.message,
        text,
        reply_markup=categories_menu_keyboard(categories, mode),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.callback_query(BookCB.filter())
async def recipes_book_menu(callback: CallbackQuery, category_service: CategoryService) -> None:
    """Кнопка «Книга рецептов» — список категорий каталога."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return

    categories = await category_service.get_all_category()
    if not categories:
        await safe_edit(
            callback.message,
            "Книга рецептов пока пуста.",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    await safe_edit(
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
    category_service: CategoryService,
    recipe_service: RecipeService,
    redis: Redis,
) -> None:
    """Выбор категории книги рецептов."""
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    category_slug = callback_data.slug
    user_id = callback.from_user.id

    try:
        category_id, category_name = await category_service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        logger.warning("Категория книги рецептов не найдена: slug=%s", category_slug)
        await safe_edit(
            callback.message,
            "Выбранная категория не найдена. Откройте «Книгу рецептов» и выберите раздел заново.",
            reply_markup=home_keyboard(),
        )
        return

    pairs = await recipe_service.get_public_recipes_ids_and_titles(category_id, exclude_user_id=user_id)
    if not pairs:
        await safe_edit(
            callback.message,
            f"В категории «{category_name}» пока нет рецептов с видео.",
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

    markup = recipes_list_keyboard(
        pairs,
        page=0,
        per_page=recipes_per_page,
        category_slug=build_book_slug(category_slug),
        mode=RecipeMode.SHOW,
        categories_callback=BookCB(),
    )
    await safe_edit(
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
    category_service: CategoryService,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Выбор категории пользователя: показать список или случайный рецепт."""
    await callback.answer()
    if not callback.from_user or not isinstance(callback.message, Message):
        return
    category_slug = callback_data.slug
    mode = RecipeMode(callback_data.mode)
    user_id = callback.from_user.id

    if mode is RecipeMode.RANDOM:
        await _handle_random_from_category(
            callback.message, category_service, recipe_service, redis, bot, user_id, category_slug
        )
    else:
        await _handle_show_from_category(
            callback.message, category_service, recipe_service, redis, user_id, category_slug, mode
        )


async def _handle_random_from_category(
    message: Message,
    category_service: CategoryService,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
    user_id: int,
    category_slug: str,
) -> None:
    """Сценарий выдачи случайного рецепта из категории."""
    try:
        category_id, category_name = await category_service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        await safe_edit(message, "Категория не найдена.", reply_markup=home_keyboard())
        return

    random_markup = random_recipe_keyboard(category_slug)
    chat_id = message.chat.id

    await delete_tracked_messages(bot, redis, user_id=user_id, chat_id=chat_id)

    recipe = await recipe_service.get_random_recipe(user_id, category_id)
    if not recipe:
        await send_and_track(
            bot,
            redis,
            chat_id=chat_id,
            text="👉 🍽 Здесь появится ваш рецепт, когда вы что-нибудь сохраните.",
            user_id=user_id,
            reply_markup=random_markup,
        )
        return

    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    text = f"Вот случайный рецепт из категории '{category_name}':\n\n{build_existing_recipe_text(recipe)}"
    if video_url:
        await answer_video_and_track(message, redis, video_url, user_id=user_id)
    await answer_and_track(
        message,
        redis,
        text,
        user_id=user_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=random_markup,
    )


async def _handle_show_from_category(
    message: Message,
    category_service: CategoryService,
    recipe_service: RecipeService,
    redis: Redis,
    user_id: int,
    category_slug: str,
    mode: RecipeMode,
) -> None:
    """Сценарий показа списка рецептов в категории."""
    try:
        category_id, category_name = await category_service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        logger.warning("Категория пользователя не найдена: slug=%s user_id=%s", category_slug, user_id)
        await safe_edit(
            message, "Выбранная категория не найдена. Откройте раздел заново.", reply_markup=home_keyboard()
        )
        return

    pairs = await recipe_service.get_all_recipes_ids_and_titles(user_id, category_id) if category_id else []
    if not pairs:
        await safe_edit(message, f"У вас нет рецептов в категории «{category_name}».", reply_markup=home_keyboard())
        return

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

    markup = recipes_list_keyboard(
        pairs,
        page=0,
        per_page=recipes_per_page,
        category_slug=category_slug,
        mode=mode,
    )
    await safe_edit(
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
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Открытие карточки выбранного рецепта."""
    await callback.answer()
    if not callback.from_user:
        return
    category_slug, mode_str, recipe_id = callback_data.category, callback_data.mode, callback_data.recipe_id
    user_id = callback.from_user.id

    await delete_message_safely(callback.message)

    state = RecipesStateData.from_dict(await RecipeActionCacheRepository.get(redis, user_id, "recipes_state"))
    keyboard = choice_recipe_keyboard(
        recipe_id,
        state.recipes_page,
        category_slug,
        mode_str,
        add_to_self=is_book_slug(category_slug),
        can_manage=mode_str == RecipeMode.SHOW.value and not is_book_slug(category_slug),
    )

    recipe = await recipe_service.get_recipe_for_view(recipe_id)
    chat_id = callback.message.chat.id if isinstance(callback.message, Message) else None
    if not recipe:
        if chat_id is not None:
            await send_and_track(
                bot, redis, chat_id=chat_id, text="❌ Рецепт не найден.", user_id=user_id, reply_markup=home_keyboard()
            )
        return

    if not isinstance(callback.message, Message):
        return
    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        await answer_video_and_track(callback.message, redis, video_url, user_id=user_id)
    await answer_and_track(
        callback.message,
        redis,
        build_existing_recipe_text(recipe),
        user_id=user_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )
