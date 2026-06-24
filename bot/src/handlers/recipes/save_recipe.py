import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, User

from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.pipeline_drafts import PipelineDraftStore
from bot.src.keyboards.callback_data import CatCB, SaveCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import categories_save_keyboard
from bot.src.recipe_flow.states import SaveRecipeStates
from packages.redis.data_models import PipelineDraft
from packages.services.category_service import CategoryService
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="save_recipe")


@router.callback_query(SaveCB.filter(F.action == "start"))
async def start_save_recipe(
    callback: CallbackQuery,
    callback_data: SaveCB,
    state: FSMContext,
    user: User,
    category_service: CategoryService,
    pipeline_draft_store: PipelineDraftStore,
    message_service: MessageService,
) -> None:
    """Кнопка «Сохранить рецепт» — предложить выбрать категорию."""
    await callback.answer()
    pipeline_id = callback_data.pipeline_id
    categories = await category_service.get_all_category()
    entry = await pipeline_draft_store.get(pipeline_id) or PipelineDraft()
    title = entry.title or ""

    await message_service.safe_edit(
        callback.message,
        f"🔖 <b>Выберете категорию для этого рецепта:</b>\n\n🍽 <b>Название рецепта:</b>\n{title}\n\n",
        reply_markup=categories_save_keyboard(categories, pipeline_id),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(SaveRecipeStates.CHOOSE_CATEGORY)


@router.callback_query(SaveCB.filter(F.action == "cancel"))
async def cancel_recipe_save(
    callback: CallbackQuery,
    callback_data: SaveCB,
    state: FSMContext,
    pipeline_draft_store: PipelineDraftStore,
    message_service: MessageService,
) -> None:
    """Кнопка «Отмена» — чистим черновик и выходим из сценария."""
    await callback.answer()
    await pipeline_draft_store.delete(callback_data.pipeline_id)
    await state.clear()
    await message_service.safe_edit(
        callback.message,
        "Рецепт не сохранен.",
        reply_markup=home_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(CatCB.filter(F.mode == "save"), SaveRecipeStates.CHOOSE_CATEGORY)
async def save_recipe(
    callback: CallbackQuery,
    callback_data: CatCB,
    state: FSMContext,
    user: User,
    category_service: CategoryService,
    recipe_service: RecipeService,
    pipeline_draft_store: PipelineDraftStore,
    message_service: MessageService,
) -> None:
    """Привязка распознанного рецепта к пользователю и выбранной категории."""
    await callback.answer()
    category_slug, pipeline_id = callback_data.slug, callback_data.pipeline_id
    entry = await pipeline_draft_store.get(pipeline_id) or PipelineDraft()
    recipe_id = entry.recipe_id
    title = entry.title or "Не указано"

    if not recipe_id:
        logger.warning("Черновик рецепта не найден в save_recipe (pipeline_id=%s)", pipeline_id)
        await state.clear()
        await message_service.safe_edit(
            callback.message,
            "❗️ Не удалось найти черновик рецепта. Пожалуйста, отправьте ссылку заново.",
            reply_markup=home_keyboard(),
        )
        return

    try:
        category = await category_service.get_id_and_name_by_slug_cached(category_slug)
        await recipe_service.link_recipe_to_user(int(recipe_id), user.id, category.id)
    except Exception as e:
        logger.exception("Ошибка при сохранении рецепта: %s", e)
        await state.clear()
        await message_service.safe_edit(
            callback.message,
            "❗️ Произошла ошибка при сохранении рецепта. Попробуйте позже.",
            reply_markup=home_keyboard(),
        )
        return

    await message_service.safe_edit(
        callback.message,
        f"✅ Ваш рецепт успешно сохранен!\n\n"
        f"🍽 <b>Название рецепта:</b>\n{title}\n\n"
        f"🔖 <b>Категория:</b> {category.name}",
        parse_mode=ParseMode.HTML,
        reply_markup=home_keyboard(),
    )
    await pipeline_draft_store.delete(pipeline_id)
    await state.clear()
