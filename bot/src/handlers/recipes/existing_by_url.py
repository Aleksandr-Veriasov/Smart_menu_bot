import logging
import secrets

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from bot.src.keyboards.callback_data import UrlCB
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import (
    url_candidate_category_keyboard,
    url_candidate_list_keyboard,
    url_candidate_recipe_keyboard,
)
from bot.src.utils.messaging import (
    delete_message_safely,
    delete_messages,
    safe_edit,
    send_and_track,
    send_video_and_track,
)
from bot.src.utils.recipe_text import build_existing_recipe_text
from packages.redis.repository import UrlCandidateCacheRepository
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


def extract_allowed_recipe_ids(state: dict) -> list[int]:
    """
    Возвращает допустимые recipe_id из сохранённого state с сохранением порядка.
    Игнорирует невалидные значения и дубликаты.
    """
    recipe_ids: list[int] = []
    seen: set[int] = set()
    for value in state.get("recipe_ids") or []:
        if not isinstance(value, int | str) or not str(value).isdigit():
            continue
        recipe_id = int(value)
        if recipe_id in seen:
            continue
        seen.add(recipe_id)
        recipe_ids.append(recipe_id)
    return recipe_ids


async def maybe_handle_multiple_existing_recipes(
    *,
    message: Message,
    recipe_service: RecipeService,
    redis: Redis,
    original_url: str,
    candidates: list[int],
) -> bool:
    """
    Если кандидатов >= 2, сохраняет список в Redis и отправляет пользователю кнопки с названиями.
    Возвращает True, если обработано.
    """
    if not message.from_user:
        return False
    user_id = int(message.from_user.id)
    if len(candidates) < 2:
        return False

    recipe_titles = await recipe_service.get_titles_for_ids(candidates)

    sid = secrets.token_urlsafe(6).replace("-", "").replace("_", "")
    payload = {"url": original_url, "recipe_ids": [int(x) for x in candidates], "v": 1}
    await UrlCandidateCacheRepository.set(redis, user_id=user_id, sid=sid, payload=payload)

    sent = await send_and_track(
        message.bot,
        redis,
        chat_id=message.chat.id,
        text="По этой ссылке найдено несколько рецептов. Выберите нужный:",
        user_id=user_id,
        reply_markup=url_candidate_list_keyboard(sid, recipe_titles),
    )
    await UrlCandidateCacheRepository.set_merge(
        redis,
        user_id=user_id,
        sid=sid,
        patch={
            "chat_id": int(sent.chat.id),
            "list_message_id": int(sent.message_id),
            "video_message_id": None,
            "recipe_message_id": None,
        },
    )
    return True


@router.callback_query(UrlCB.filter(F.action == "pick"))
async def show_candidate_recipe(
    callback: CallbackQuery,
    callback_data: UrlCB,
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Показ конкретного рецепта из списка кандидатов по ссылке."""
    await callback.answer()
    if not callback.from_user:
        return
    sid, recipe_id = callback_data.sid, callback_data.recipe_id

    user_id = int(callback.from_user.id)
    state = await UrlCandidateCacheRepository.get(redis, user_id=user_id, sid=sid)
    if not state:
        await safe_edit(callback.message, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при показе кандидата", user_id, sid)
        return

    allowed = extract_allowed_recipe_ids(state)
    if recipe_id not in allowed:
        await safe_edit(callback.message, UNAVAILABLE_RECIPE_TEXT, reply_markup=home_keyboard())
        logger.warning("recipe_id=%s не в allowed (user_id=%s, sid=%s)", recipe_id, user_id, sid)
        return

    recipe, already_linked = await recipe_service.get_recipe_with_link_status(int(recipe_id), int(user_id))
    if recipe is None:
        await safe_edit(callback.message, "Рецепт не найден.", reply_markup=home_keyboard())
        logger.warning("Рецепт recipe_id=%s не найден при показе кандидата", recipe_id)
        return

    chat_id = _message_chat_id(callback.message) or int(state.get("chat_id") or 0)
    if not chat_id:
        return

    # Удаляем текущее сообщение с кнопкой "Назад", чтобы не засорять чат.
    await delete_message_safely(callback.message)

    header = "Этот рецепт у Вас уже сохранён ✅" if already_linked else "Рецепт из каталога ✅"
    body = f"{header}\n\n{build_existing_recipe_text(recipe)}"

    video_mid = None
    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        try:
            video_msg = await send_video_and_track(bot, redis, chat_id=chat_id, video=video_url, user_id=user_id)
            video_mid = int(video_msg.message_id)
        except TelegramBadRequest as e:
            logger.warning("Не удалось отправить видео для recipe_id=%s: %s", recipe_id, e)

    recipe_msg = await send_and_track(
        bot,
        redis,
        chat_id=chat_id,
        text=body,
        user_id=user_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=url_candidate_recipe_keyboard(sid=sid, recipe_id=recipe_id, already_linked=already_linked),
    )

    await UrlCandidateCacheRepository.set_merge(
        redis,
        user_id=user_id,
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
    recipe_service: RecipeService,
    redis: Redis,
    bot: Bot,
) -> None:
    """Возврат к списку рецептов, найденных по ссылке."""
    await callback.answer()
    if not callback.from_user:
        return
    sid = callback_data.sid

    user_id = int(callback.from_user.id)
    state = await UrlCandidateCacheRepository.get(redis, user_id=user_id, sid=sid)
    if not state:
        await safe_edit(callback.message, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при показе списка", user_id, sid)
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
    await delete_messages(bot, chat_id=chat_id, message_ids=msg_ids_to_delete)

    recipe_ids = extract_allowed_recipe_ids(state)
    recipe_titles = await recipe_service.get_titles_for_ids(recipe_ids)

    sent = await send_and_track(
        bot,
        redis,
        chat_id=chat_id,
        text="По этой ссылке найдено несколько рецептов. Выберите нужный:",
        user_id=user_id,
        reply_markup=url_candidate_list_keyboard(sid, recipe_titles),
    )
    await UrlCandidateCacheRepository.set_merge(
        redis,
        user_id=user_id,
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
    category_service: CategoryService,
    redis: Redis,
) -> None:
    """Запрос категории для добавления рецепта, выбранного по ссылке."""
    await callback.answer()
    if not callback.from_user:
        return
    sid, recipe_id = callback_data.sid, callback_data.recipe_id

    user_id = int(callback.from_user.id)
    state = await UrlCandidateCacheRepository.get(redis, user_id=user_id, sid=sid)
    if not state:
        await safe_edit(callback.message, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при добавлении", user_id, sid)
        return

    allowed = extract_allowed_recipe_ids(state)
    if recipe_id not in allowed:
        await safe_edit(callback.message, UNAVAILABLE_RECIPE_TEXT, reply_markup=home_keyboard())
        logger.warning("recipe_id=%s не в allowed (user_id=%s, sid=%s)", recipe_id, user_id, sid)
        return

    categories = await category_service.get_all_category()
    await safe_edit(
        callback.message,
        "Выберите категорию для добавления рецепта:",
        reply_markup=url_candidate_category_keyboard(sid, recipe_id, categories),
    )


@router.callback_query(UrlCB.filter(F.action == "addcat"))
async def add_candidate_recipe_choose_category(
    callback: CallbackQuery,
    callback_data: UrlCB,
    recipe_service: RecipeService,
    category_service: CategoryService,
    redis: Redis,
) -> None:
    """Привязка выбранного по ссылке рецепта к категории пользователя."""
    await callback.answer()
    if not callback.from_user:
        return
    sid, recipe_id, slug = callback_data.sid, callback_data.recipe_id, callback_data.slug

    user_id = int(callback.from_user.id)
    category_id, _ = await category_service.get_id_and_name_by_slug_cached(slug)

    created = await recipe_service.link_recipe_to_user(recipe_id, user_id, category_id)
    message_text = "✅ Рецепт успешно сохранён." if created else "ℹ️ Рецепт уже есть у вас, обновили категорию."

    # Пользователь уже выбрал рецепт и категорию — чистим состояние выбора по ссылке.
    await UrlCandidateCacheRepository.delete(redis, user_id=user_id, sid=sid)

    await safe_edit(callback.message, message_text, reply_markup=home_keyboard())
