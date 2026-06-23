import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User
from redis.asyncio import Redis

from bot.src.keyboards.callback_data import NavCB, RecipeCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import delete_confirm_keyboard
from bot.src.recipe_flow.states import DeleteRecipeStates
from bot.src.utils.messaging import delete_tracked_messages, safe_edit, send_and_track
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="delete_recipe")


@router.callback_query(RecipeCB.filter(F.action == "delete"))
async def delete_recipe(
    callback: CallbackQuery,
    callback_data: RecipeCB,
    state: FSMContext,
    recipe_service: RecipeService,
) -> None:
    """Кнопка «Удалить рецепт» — запрос подтверждения."""
    await callback.answer()
    recipe_id = callback_data.recipe_id
    recipe_name = await recipe_service.get_recipe_name(recipe_id)
    if not recipe_name:
        await safe_edit(callback.message, "Рецепт не найден.", reply_markup=home_keyboard())
        logger.warning("Рецепт recipe_id=%s не найден в delete_recipe", recipe_id)
        return

    await state.set_state(DeleteRecipeStates.CONFIRM_DELETE)
    await state.update_data(recipe_id=recipe_id)
    await safe_edit(
        callback.message,
        f"Вы точно хотите удалить рецепт <b>{recipe_name}</b>?",
        reply_markup=delete_confirm_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(NavCB.filter(F.action == "delete"), DeleteRecipeStates.CONFIRM_DELETE)
async def confirm_delete(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Подтверждение удаления рецепта."""
    await callback.answer()
    data = await state.get_data()
    recipe_id = data.get("recipe_id")
    await state.clear()

    if not recipe_id:
        await safe_edit(callback.message, "Не смог понять ID рецепта.", reply_markup=home_keyboard())
        logger.error("recipe_id отсутствует в state при подтверждении удаления (user_id=%s)", user.id)
        return

    await recipe_service.delete_recipe(user.id, recipe_id)

    if isinstance(callback.message, Message):
        chat_id = callback.message.chat.id
        await delete_tracked_messages(bot, redis, user_id=user.id, chat_id=chat_id)
        await send_and_track(
            bot,
            redis,
            chat_id=chat_id,
            text="✅ Рецепт успешно удалён.",
            user_id=user.id,
            reply_markup=home_keyboard(),
            parse_mode=ParseMode.HTML,
        )
    else:
        await safe_edit(callback.message, "✅ Рецепт успешно удалён.", reply_markup=home_keyboard())


@router.callback_query(NavCB.filter(F.action == "cancel"), DeleteRecipeStates.CONFIRM_DELETE)
async def cancel_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена удаления рецепта."""
    await callback.answer()
    await state.clear()
    await safe_edit(callback.message, "Отменено.", reply_markup=home_keyboard())
