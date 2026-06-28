import logging

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, User

from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.url_candidates import UrlCandidateStore
from bot.src.interactions.url_candidates import extract_allowed_recipe_ids
from bot.src.keyboards.callback_data import UrlCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import (
    url_candidate_category_keyboard,
    url_candidate_list_keyboard,
    url_candidate_recipe_keyboard,
)
from bot.src.utils.recipe_text import build_existing_recipe_text
from packages.services.category_service import CategoryService
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="existing_by_url")

STALE_LIST_TEXT = "Список по ссылке устарел. Пришлите ссылку ещё раз."
UNAVAILABLE_RECIPE_TEXT = "Этот рецепт больше недоступен в списке."


def _message_chat_id(message: Message | None) -> int | None:
    """Возвращает chat_id из сообщения callback-а, если оно доступно."""
    if not isinstance(message, Message):
        return None
    return int(message.chat.id)


@router.callback_query(UrlCB.filter(F.action == "pick"))
async def show_candidate_recipe(
    callback: CallbackQuery,
    callback_data: UrlCB,
    user: User,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
    url_candidate_store: UrlCandidateStore,
) -> None:
    """Показ конкретного рецепта из списка кандидатов по ссылке."""
    await callback.answer()
    sid, recipe_id = callback_data.sid, callback_data.recipe_id

    state = await url_candidate_store.get(sid=sid)
    if not state:
        await message_service.safe_edit(callback.message, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при показе кандидата", user.id, sid)
        return

    allowed = extract_allowed_recipe_ids(state)
    if recipe_id not in allowed:
        await message_service.safe_edit(callback.message, UNAVAILABLE_RECIPE_TEXT, reply_markup=home_keyboard())
        logger.warning("recipe_id=%s не в allowed (user_id=%s, sid=%s)", recipe_id, user.id, sid)
        return

    recipe, already_linked = await recipe_service.get_recipe_with_link_status(int(recipe_id), user.id)
    if recipe is None:
        await message_service.safe_edit(callback.message, "Рецепт не найден.", reply_markup=home_keyboard())
        logger.warning("Рецепт recipe_id=%s не найден при показе кандидата", recipe_id)
        return

    chat_id = _message_chat_id(callback.message) or int(state.get("chat_id") or 0)
    if not chat_id:
        return

    # Удаляем текущее сообщение с кнопкой "Назад", чтобы не засорять чат.
    await message_service.delete_message_safely(callback.message)

    header = "Этот рецепт у Вас уже сохранён ✅" if already_linked else "Рецепт из каталога ✅"
    body = f"{header}\n\n{build_existing_recipe_text(recipe)}"

    video_mid = None
    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        try:
            video_msg = await message_service.send_video_and_track(
                bot,
                chat_id=chat_id,
                video=video_url,
            )
            video_mid = int(video_msg.message_id)
        except TelegramBadRequest as e:
            logger.warning("Не удалось отправить видео для recipe_id=%s: %s", recipe_id, e)

    recipe_msg = await message_service.send_and_track(
        bot,
        chat_id=chat_id,
        text=body,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=url_candidate_recipe_keyboard(sid=sid, recipe_id=recipe_id, already_linked=already_linked),
    )

    await url_candidate_store.set_merge(
        sid=sid,
        patch={
            "chat_id": chat_id,
            "list_message_id": None,
            "video_message_id": video_mid,
            "recipe_message_id": int(recipe_msg.message_id),
        },
    )


@router.callback_query(UrlCB.filter(F.action == "list"))
async def show_candidates_list(
    callback: CallbackQuery,
    callback_data: UrlCB,
    user: User,
    recipe_service: RecipeService,
    bot: Bot,
    message_service: MessageService,
    url_candidate_store: UrlCandidateStore,
) -> None:
    """Возврат к списку рецептов, найденных по ссылке."""
    await callback.answer()
    sid = callback_data.sid

    state = await url_candidate_store.get(sid=sid)
    if not state:
        await message_service.safe_edit(callback.message, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при показе списка", user.id, sid)
        return

    chat_id = _message_chat_id(callback.message) or int(state.get("chat_id") or 0)
    if not chat_id:
        return

    # Удаляем текущее сообщение и видео (если было), чтобы не засорять чат.
    msg_ids_to_delete: list[int] = []
    if isinstance(callback.message, Message):
        msg_ids_to_delete.append(int(callback.message.message_id))
    if state.get("video_message_id"):
        msg_ids_to_delete.append(int(state["video_message_id"]))
    await message_service.delete_messages(bot, chat_id=chat_id, message_ids=msg_ids_to_delete)

    recipe_ids = extract_allowed_recipe_ids(state)
    recipe_titles = await recipe_service.get_titles_for_ids(recipe_ids)

    sent = await message_service.send_and_track(
        bot,
        chat_id=chat_id,
        text="По этой ссылке найдено несколько рецептов. Выберите нужный:",
        reply_markup=url_candidate_list_keyboard(sid, recipe_titles),
    )
    await url_candidate_store.set_merge(
        sid=sid,
        patch={
            "chat_id": chat_id,
            "list_message_id": int(sent.message_id),
            "video_message_id": None,
            "recipe_message_id": None,
        },
    )


@router.callback_query(UrlCB.filter(F.action == "add"))
async def add_candidate_recipe(
    callback: CallbackQuery,
    callback_data: UrlCB,
    user: User,
    category_service: CategoryService,
    url_candidate_store: UrlCandidateStore,
    message_service: MessageService,
) -> None:
    """Запрос категории для добавления рецепта, выбранного по ссылке."""
    await callback.answer()
    sid, recipe_id = callback_data.sid, callback_data.recipe_id

    state = await url_candidate_store.get(sid=sid)
    if not state:
        await message_service.safe_edit(callback.message, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при добавлении", user.id, sid)
        return

    allowed = extract_allowed_recipe_ids(state)
    if recipe_id not in allowed:
        await message_service.safe_edit(callback.message, UNAVAILABLE_RECIPE_TEXT, reply_markup=home_keyboard())
        logger.warning("recipe_id=%s не в allowed (user_id=%s, sid=%s)", recipe_id, user.id, sid)
        return

    categories = await category_service.get_all_category()
    await message_service.safe_edit(
        callback.message,
        "Выберите категорию для добавления рецепта:",
        reply_markup=url_candidate_category_keyboard(sid, recipe_id, categories),
    )


@router.callback_query(UrlCB.filter(F.action == "addcat"))
async def add_candidate_recipe_choose_category(
    callback: CallbackQuery,
    callback_data: UrlCB,
    user: User,
    recipe_service: RecipeService,
    category_service: CategoryService,
    url_candidate_store: UrlCandidateStore,
    message_service: MessageService,
) -> None:
    """Привязка выбранного по ссылке рецепта к категории пользователя."""
    await callback.answer()
    sid, recipe_id, slug = callback_data.sid, callback_data.recipe_id, callback_data.slug

    category = await category_service.get_id_and_name_by_slug_cached(slug)

    created = await recipe_service.link_recipe_to_user(recipe_id, user.id, category.id)
    message_text = "✅ Рецепт успешно сохранён." if created else "ℹ️ Рецепт уже есть у вас, обновили категорию."

    # Пользователь уже выбрал рецепт и категорию — чистим состояние выбора по ссылке.
    await url_candidate_store.delete(sid=sid)

    await message_service.safe_edit(callback.message, message_text, reply_markup=home_keyboard())
