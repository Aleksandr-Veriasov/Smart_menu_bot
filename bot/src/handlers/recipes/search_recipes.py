import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User
from redis.asyncio import Redis

from bot.src.keyboards.callback_data import NavCB, SearchCB, SearchTypeCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import (
    cancel_keyboard,
    recipes_list_keyboard,
    search_type_keyboard,
)
from bot.src.recipe_flow.list_state import RecipesStateData
from bot.src.recipe_flow.modes import RecipeMode
from bot.src.recipe_flow.states import SearchRecipeStates
from bot.src.utils.messaging import answer_and_track, delete_tracked_messages, safe_edit
from packages.common_settings.settings import settings
from packages.redis.repository import RecipeActionCacheRepository
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="search_recipes")


@router.callback_query(SearchCB.filter(F.action == "start"))
async def start_search(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Поиск рецептов» — выбор способа поиска."""
    await callback.answer()
    await safe_edit(
        callback.message,
        "Поиск идёт только по вашим сохранённым рецептам.\n\n"
        "Выберите способ поиска:\n"
        "<b>• по названию</b> — ищем совпадения в заголовке рецепта\n"
        "<b>• по ингредиентам</b> — ищем совпадения в списке ингредиентов",
        reply_markup=search_type_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(SearchRecipeStates.CHOOSE_TYPE)


@router.callback_query(SearchTypeCB.filter(), SearchRecipeStates.CHOOSE_TYPE)
async def choose_search_type(callback: CallbackQuery, callback_data: SearchTypeCB, state: FSMContext) -> None:
    """Выбор типа поиска и запрос текста."""
    await callback.answer()
    if callback_data.kind == "title":
        await safe_edit(callback.message, "Введите слово из названия рецепта:", reply_markup=cancel_keyboard())
        await state.set_state(SearchRecipeStates.WAIT_TITLE)
    else:
        await safe_edit(callback.message, "Введите ингредиент для поиска:", reply_markup=cancel_keyboard())
        await state.set_state(SearchRecipeStates.WAIT_INGREDIENT)


async def _run_search(
    message: Message,
    state: FSMContext,
    user: User,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
    *,
    search_type: str,
) -> None:
    """Общая логика поиска по названию/ингредиенту и вывода результатов."""
    query = (message.text or "").strip()
    label = "названию" if search_type == "title" else "ингредиенту"
    empty_hint = "Пусто. Введите слово ещё раз." if search_type == "title" else "Пусто. Введите ингредиент ещё раз."
    if not query:
        await answer_and_track(message, redis, empty_hint)
        return

    await delete_tracked_messages(bot, redis, user_id=user.id, chat_id=message.chat.id)

    if search_type == "title":
        items = await recipe_service.search_by_title(user.id, query)
    else:
        items = await recipe_service.search_by_ingredient(user.id, query)

    if not items:
        await state.clear()
        await answer_and_track(
            message,
            redis,
            f"Ничего не найдено по {label}: <b>{query}</b>",
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    recipes_per_page = settings.telegram.recipes_per_page
    recipes_total_pages = (len(items) + recipes_per_page - 1) // recipes_per_page
    search_state = RecipesStateData.for_search(
        search_type=search_type,
        query=query,
        recipes_total_pages=recipes_total_pages,
        search_items=items,
    )
    await RecipeActionCacheRepository.set(redis, user.id, "recipes_state", search_state.to_dict())

    markup = recipes_list_keyboard(
        items,
        page=0,
        per_page=recipes_per_page,
        category_slug="search",
        mode=RecipeMode.SEARCH,
    )
    await answer_and_track(
        message,
        redis,
        f"Результаты поиска по {label}: <b>{query}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    await state.clear()


@router.message(SearchRecipeStates.WAIT_TITLE, F.text)
async def handle_title_query(
    message: Message,
    state: FSMContext,
    user: User,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Поиск по названию."""
    await _run_search(message, state, user, recipe_service, redis, bot, search_type="title")


@router.message(SearchRecipeStates.WAIT_INGREDIENT, F.text)
async def handle_ingredient_query(
    message: Message,
    state: FSMContext,
    user: User,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Поиск по ингредиенту."""
    await _run_search(message, state, user, recipe_service, redis, bot, search_type="ingredient")


@router.callback_query(
    NavCB.filter(F.action == "cancel"),
    StateFilter(
        SearchRecipeStates.CHOOSE_TYPE,
        SearchRecipeStates.WAIT_TITLE,
        SearchRecipeStates.WAIT_INGREDIENT,
    ),
)
async def cancel_search(callback: CallbackQuery, state: FSMContext, user: User, redis: Redis) -> None:
    """Отмена поиска."""
    await callback.answer()
    await RecipeActionCacheRepository.delete(redis, user.id, "recipes_state")
    await state.clear()
    await safe_edit(callback.message, "Поиск отменен.", reply_markup=home_keyboard())
