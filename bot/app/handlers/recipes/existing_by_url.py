import logging
import secrets

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest

from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import (
    home_keyboard,
    url_candidate_category_keyboard,
    url_candidate_list_keyboard,
    url_candidate_recipe_keyboard,
)
from bot.app.services.category_service import CategoryService
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db_and_redis
from bot.app.utils.message_cache import (
    send_message_and_cache,
    send_video_and_cache,
)
from bot.app.utils.message_utils import (
    build_existing_recipe_text,
    delete_message_safely,
    delete_messages,
    safe_edit_message,
)
from packages.db.repository import RecipeRepository, RecipeUserRepository
from packages.redis.repository import (
    CategoryCacheRepository,
    RecipeCacheRepository,
    UrlCandidateCacheRepository,
)

logger = logging.getLogger(__name__)

STALE_LIST_TEXT = "Список по ссылке устарел. Пришлите ссылку ещё раз."
UNAVAILABLE_RECIPE_TEXT = "Этот рецепт больше недоступен в списке."


def parse_sid_and_recipe_id(data: str) -> tuple[str, int] | None:
    """Извлекает sid и recipe_id из callback вида prefix:<sid>:<recipe_id>."""
    try:
        _, sid, recipe_id_str = data.split(":", 2)
        return sid, int(recipe_id_str)
    except ValueError:
        logger.warning("Не удалось распарсить sid и recipe_id из callback data: %s", data)
        return None


def parse_sid(data: str) -> str | None:
    """Извлекает sid из callback вида prefix:<sid>."""
    try:
        _, sid = data.split(":", 1)
        return sid
    except ValueError:
        logger.warning("Не удалось распарсить sid из callback data: %s", data)
        return None


def parse_sid_recipe_id_and_slug(data: str) -> tuple[str, int, str] | None:
    """Извлекает sid, recipe_id и slug из callback вида prefix:<sid>:<recipe_id>:<slug>."""
    try:
        _, sid, recipe_id_str, slug = data.split(":", 3)
        return sid, int(recipe_id_str), slug
    except ValueError:
        logger.warning("Не удалось распарсить sid, recipe_id и slug из callback data: %s", data)
        return None


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


async def render_candidates_message(
    *,
    update: Update,
    context: PTBContext,
    sid: str,
    recipe_titles: list[tuple[int, str]],
) -> Message | None:
    """Отправляет сообщение со списком найденных рецептов и кнопками выбора."""
    msg = update.effective_message
    if not msg:
        return None
    sent = await send_message_and_cache(
        update,
        context,
        msg.chat_id,
        "По этой ссылке найдено несколько рецептов. Выберите нужный:",
        reply_markup=url_candidate_list_keyboard(sid, recipe_titles),
    )
    # Если не удалось отправить сообщение, всё равно сохраняем список кандидатов в Redis, чтобы не потерять их.
    return sent


async def maybe_handle_multiple_existing_recipes(
    *, update: Update, context: PTBContext, original_url: str, candidates: list[int]
) -> bool:
    """
    Если кандидатов >= 2, сохраняет список в Redis и отправляет пользователю кнопки с названиями.
    Возвращает True, если обработано.
    """
    msg = update.effective_message
    if not msg or not msg.from_user:
        return False
    user_id = int(msg.from_user.id)
    if len(candidates) < 2:
        return False

    db, redis = get_db_and_redis(context)
    async with db.session() as session:
        rows = await RecipeRepository.get_ids_and_titles_by_ids(session, [int(x) for x in candidates])
        id_to_title = {int(row["id"]): str(row["title"]) for row in rows}
        recipe_titles = [(rid, id_to_title.get(int(rid), "")) for rid in candidates if int(rid) in id_to_title]

    sid = secrets.token_urlsafe(6).replace("-", "").replace("_", "")
    payload = {"url": original_url, "recipe_ids": [int(x) for x in candidates], "v": 1}
    await UrlCandidateCacheRepository.set(redis, user_id=user_id, sid=sid, payload=payload)

    sent = await render_candidates_message(update=update, context=context, sid=sid, recipe_titles=recipe_titles)
    if sent:
        await UrlCandidateCacheRepository.set_merge(
            redis,
            user_id=user_id,
            sid=sid,
            patch={
                "chat_id": int(sent.chat_id),
                "list_message_id": int(sent.message_id),
                "video_message_id": None,
                "recipe_message_id": None,
            },
        )
    return True


async def show_candidate_recipe(update: Update, context: PTBContext) -> None:
    """
    Entry-point: r"^urlpick:[A-Za-z0-9]+:\\d+$"
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.from_user or not cq.data:
        return

    parsed = parse_sid_and_recipe_id(cq.data)
    if parsed is None:
        return
    sid, recipe_id = parsed

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    state = await UrlCandidateCacheRepository.get(redis, user_id=user_id, sid=sid)
    if not state:
        await safe_edit_message(cq, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при показе кандидата", user_id, sid)
        return

    allowed = extract_allowed_recipe_ids(state)
    if recipe_id not in allowed:
        await safe_edit_message(cq, UNAVAILABLE_RECIPE_TEXT, reply_markup=home_keyboard())
        logger.warning(
            "recipe_id=%s не в списке allowed для user_id=%s, sid=%s при показе кандидата", recipe_id, user_id, sid
        )
        return

    async with db.session() as session:
        recipe = await RecipeRepository.get_recipe_with_connections(session, int(recipe_id))
        if not recipe:
            recipe_not_found = True
            already_linked = False
        else:
            recipe_not_found = False
            already_linked = await RecipeUserRepository.is_linked(session, int(recipe_id), int(user_id))

    if recipe_not_found:
        await safe_edit_message(cq, "Рецепт не найден.", reply_markup=home_keyboard())
        logger.warning("Рецепт recipe_id=%s не найден при показе кандидата", recipe_id)
        return

    chat_id = int(getattr(cq.message, "chat_id", None) or state.get("chat_id") or 0)
    if not chat_id:
        return

    # Удаляем текущее сообщение с кнопкой "Назад" и видео (если было), чтобы не засорять чат.
    await delete_message_safely(cq.message)
    text = "Рецепт найден, но не удалось загрузить его детали."
    if recipe is not None:
        text = build_existing_recipe_text(recipe)

    header = "Этот рецепт у Вас уже сохранён ✅" if already_linked else "Рецепт из каталога ✅"
    body = f"{header}\n\n{text}"

    # Отправляем видео (если есть) и сохраняем его message_id для последующего удаления, чтобы не засорять чат.
    video_mid = None
    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    if video_url:
        try:
            video_msg = await send_video_and_cache(update, context, chat_id, video_url, user_id=user_id)
            video_mid = int(video_msg.message_id)
        except BadRequest as e:
            logger.warning("Не удалось отправить видео для recipe_id=%s: %s", recipe_id, e)

    recipe_msg = await send_message_and_cache(
        update,
        context,
        chat_id,
        body,
        user_id=user_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=url_candidate_recipe_keyboard(
            sid=sid,
            recipe_id=recipe_id,
            already_linked=already_linked,
        ),
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


async def show_candidates_list(update: Update, context: PTBContext) -> None:
    """
    Entry-point: r"^urllist:[A-Za-z0-9]+$"
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.from_user or not cq.data:
        return
    sid = parse_sid(cq.data)
    if sid is None:
        return

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    state = await UrlCandidateCacheRepository.get(redis, user_id=user_id, sid=sid)
    if not state:
        await safe_edit_message(cq, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при показе списка кандидатов", user_id, sid)
        return

    chat_id = int(getattr(cq.message, "chat_id", None) or state.get("chat_id") or 0)
    if not chat_id:
        return

    # Удаляем текущее сообщение с кнопкой "Назад" и видео (если было), чтобы не засорять чат.
    msg_ids_to_delete: list[int] = []
    if cq.message:
        msg_ids_to_delete.append(int(cq.message.message_id))
    if state.get("video_message_id"):
        msg_ids_to_delete.append(int(state["video_message_id"]))
    await delete_messages(context, chat_id=chat_id, message_ids=msg_ids_to_delete)

    recipe_ids = extract_allowed_recipe_ids(state)
    async with db.session() as session:
        rows = await RecipeRepository.get_ids_and_titles_by_ids(session, recipe_ids)
        id_to_title = {int(row["id"]): str(row["title"]) for row in rows}
        recipe_titles = [(rid, id_to_title.get(int(rid), "")) for rid in recipe_ids if int(rid) in id_to_title]

    sent = await send_message_and_cache(
        update,
        context,
        chat_id,
        "По этой ссылке найдено несколько рецептов. Выберите нужный:",
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


async def add_candidate_recipe(update: Update, context: PTBContext) -> None:
    """
    Entry-point: r"^urladd:[A-Za-z0-9]+:\\d+$"
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.from_user or not cq.data:
        return

    parsed = parse_sid_and_recipe_id(cq.data)
    if parsed is None:
        return
    sid, recipe_id = parsed

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    state = await UrlCandidateCacheRepository.get(redis, user_id=user_id, sid=sid)
    if not state:
        await safe_edit_message(cq, STALE_LIST_TEXT, reply_markup=home_keyboard())
        logger.warning("Состояние для user_id=%s, sid=%s не найдено при добавлении кандидата", user_id, sid)
        return

    allowed = extract_allowed_recipe_ids(state)
    if recipe_id not in allowed:
        await safe_edit_message(cq, UNAVAILABLE_RECIPE_TEXT, reply_markup=home_keyboard())
        logger.warning(
            "recipe_id=%s не в списке allowed для user_id=%s, sid=%s при добавлении кандидата", recipe_id, user_id, sid
        )
        return

    service = CategoryService(db, redis)
    categories = await service.get_all_category()
    await safe_edit_message(
        cq,
        "Выберите категорию для добавления рецепта:",
        reply_markup=url_candidate_category_keyboard(sid, recipe_id, categories),
    )


async def add_candidate_recipe_choose_category(update: Update, context: PTBContext) -> None:
    """
    Entry-point: r"^urladdcat:[A-Za-z0-9]+:\\d+:[a-z0-9_-]+$"
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.from_user or not cq.data:
        return

    parsed = parse_sid_recipe_id_and_slug(cq.data)
    if parsed is None:
        return
    sid, recipe_id, slug = parsed

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    service = CategoryService(db, redis)
    category_id, _ = await service.get_id_and_name_by_slug_cached(slug)

    message_text = "✅ Рецепт успешно сохранён."
    async with db.session() as session:
        created = await RecipeUserRepository.upsert_user_link(session, recipe_id, user_id, category_id)
    if not created:
        message_text = "ℹ️ Рецепт уже есть у вас, обновили категорию."

    await CategoryCacheRepository.invalidate_user_categories(redis, user_id)
    await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(redis, user_id, category_id)

    # Пользователь уже выбрал рецепт и категорию. К списку по ссылке возвращаться не нужно.
    # Заодно подчистим состояние выбора по ссылке.
    await UrlCandidateCacheRepository.delete(redis, user_id=user_id, sid=sid)

    await safe_edit_message(cq, message_text, reply_markup=home_keyboard())
