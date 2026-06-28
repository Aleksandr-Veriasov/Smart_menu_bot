from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.src.bot_ui.messages import MessageService
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import choice_recipe_keyboard, random_recipe_keyboard
from bot.src.recipe_flow.book_slug import is_book_slug
from bot.src.recipe_flow.list_state import RecipesStateData
from bot.src.recipe_flow.modes import RecipeMode
from bot.src.utils.recipe_text import build_existing_recipe_text
from packages.services.category_service import CategoryService
from packages.services.recipe_service import RecipeService


async def show_random_recipe_from_category(
    message: Message,
    category_service: CategoryService,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
    user_id: int,
    category_slug: str,
) -> None:
    """Показывает случайный рецепт из выбранной категории пользователя."""
    try:
        category = await category_service.get_id_and_name_by_slug_cached(category_slug)
    except ValueError:
        await message_service.safe_edit(message, "Категория не найдена.", reply_markup=home_keyboard())
        return

    random_markup = random_recipe_keyboard(category_slug)
    chat_id = message.chat.id

    await message_service.delete_tracked_messages(bot, chat_id=chat_id)

    recipe = await recipe_service.get_random_recipe(user_id, category.id)
    if not recipe:
        await message_service.send_and_track(
            bot,
            chat_id=chat_id,
            text="👉 🍽 Здесь появится ваш рецепт, когда вы что-нибудь сохраните.",
            reply_markup=random_markup,
        )
        return

    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    text = f"Вот случайный рецепт из категории '{category.name}':\n\n{build_existing_recipe_text(recipe)}"
    if video_url:
        await message_service.answer_video_and_track(message, video_url)
    await message_service.answer_and_track(
        message,
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=random_markup,
    )


async def show_recipe_card(
    message: Message,
    *,
    bot: Bot,
    message_service: MessageService,
    state: FSMContext,
    recipe_service: RecipeService,
    recipe_id: int,
    category_slug: str,
    mode: str,
) -> None:
    """Открывает карточку выбранного рецепта из списка."""
    await message_service.delete_message_safely(message)

    data = await state.get_data()
    recipes_state = RecipesStateData.from_dict(data.get("recipes_state"))
    keyboard = choice_recipe_keyboard(
        recipe_id,
        recipes_state.recipes_page,
        category_slug,
        mode,
        add_to_self=is_book_slug(category_slug),
        can_manage=mode == RecipeMode.SHOW.value and not is_book_slug(category_slug),
    )

    recipe = await recipe_service.get_recipe_for_view(recipe_id)
    if not recipe:
        await message_service.send_and_track(
            bot,
            chat_id=message.chat.id,
            text="❌ Рецепт не найден.",
            reply_markup=home_keyboard(),
        )
        return

    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        await message_service.answer_video_and_track(message, video_url)
    await message_service.answer_and_track(
        message,
        build_existing_recipe_text(recipe),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )
