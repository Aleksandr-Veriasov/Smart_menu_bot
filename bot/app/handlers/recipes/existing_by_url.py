import secrets
from contextlib import suppress
from html import escape

from sqlalchemy import select
from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest

from bot.app.core.types import PTBContext
from bot.app.keyboards.builders import InlineKB
from bot.app.keyboards.inlines import home_keyboard
from bot.app.services.category_service import CategoryService
from bot.app.utils.context_helpers import get_db, get_db_and_redis, get_redis_cli
from bot.app.utils.message_cache import append_message_id_to_cache
from packages.db.models import Recipe
from packages.db.repository import RecipeRepository, RecipeUserRepository
from packages.redis.repository import (
    CategoryCacheRepository,
    RecipeActionCacheRepository,
    RecipeCacheRepository,
)

_ACTION_PREFIX = "url_candidates:"


def _action_key(sid: str) -> str:
    return f"{_ACTION_PREFIX}{sid}"


def _new_sid() -> str:
    # short, callback-safe
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")


async def _get_state(redis, *, user_id: int, sid: str) -> dict:
    return await RecipeActionCacheRepository.get(redis, user_id, _action_key(sid)) or {}


async def _set_state(redis, *, user_id: int, sid: str, patch: dict) -> dict:
    state = await _get_state(redis, user_id=user_id, sid=sid)
    state.update(patch or {})
    await RecipeActionCacheRepository.set(redis, user_id, _action_key(sid), state)
    return state


async def _delete_messages(context: PTBContext, *, chat_id: int, message_ids: list[int]) -> None:
    for mid in message_ids:
        if not mid:
            continue
        with suppress(BadRequest):
            await context.bot.delete_message(chat_id=chat_id, message_id=int(mid))


async def _render_candidates_message(
    *,
    update: Update,
    context: PTBContext,
    sid: str,
    recipe_titles: list[tuple[int, str]],
) -> Message | None:
    kb = InlineKB()
    for recipe_id, title in recipe_titles:
        t = (title or "").strip() or "Без названия"
        if len(t) > 45:
            t = t[:42] + "..."
        kb.button(text=f"▪️ {t}", callback_data=f"urlpick:{sid}:{int(recipe_id)}")
    kb.button(text="🏠 На главную", callback_data="start")

    msg = update.effective_message
    if not msg:
        return None
    sent = await msg.reply_text(
        "По этой ссылке найдено несколько рецептов. Выберите нужный:",
        reply_markup=kb.adjust(1),
    )
    await append_message_id_to_cache(update, context, sent.message_id)
    # caller persists list_message_id in state
    return sent


async def maybe_handle_multiple_existing_recipes(
    *,
    update: Update,
    context: PTBContext,
    original_url: str,
    candidates: list[int],
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

    db = get_db(context)
    async with db.session() as session:
        rows = (
            await session.execute(select(Recipe.id, Recipe.title).where(Recipe.id.in_([int(x) for x in candidates])))
        ).all()
        id_to_title = {int(r.id): str(r.title) for r in rows}
        recipe_titles = [(rid, id_to_title.get(int(rid), "")) for rid in candidates if int(rid) in id_to_title]

    sid = _new_sid()
    redis = get_redis_cli(context)
    payload = {"url": original_url, "recipe_ids": [int(x) for x in candidates], "v": 1}
    await RecipeActionCacheRepository.set(redis, user_id, _action_key(sid), payload)

    sent = await _render_candidates_message(update=update, context=context, sid=sid, recipe_titles=recipe_titles)
    if sent:
        await _set_state(
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
    cq = update.callback_query
    if not cq or not cq.data or not cq.from_user:
        return
    await cq.answer()

    try:
        _, sid, recipe_id_str = cq.data.split(":", 2)
        recipe_id = int(recipe_id_str)
    except Exception:
        return

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    state = await _get_state(redis, user_id=user_id, sid=sid)
    if not state:
        await cq.edit_message_text("Список по ссылке устарел. Пришлите ссылку ещё раз.", reply_markup=home_keyboard())
        return

    allowed = {int(x) for x in (state.get("recipe_ids") or []) if isinstance(x, int | str) and str(x).isdigit()}
    if recipe_id not in allowed:
        await cq.edit_message_text("Этот рецепт больше недоступен в списке.", reply_markup=home_keyboard())
        return

    async with db.session() as session:
        recipe = await RecipeRepository.get_recipe_with_connections(session, int(recipe_id))
        if not recipe:
            await cq.edit_message_text("Рецепт не найден.", reply_markup=home_keyboard())
            return
        already_linked = await RecipeUserRepository.is_linked(session, int(recipe_id), int(user_id))

    chat_id = int(getattr(cq.message, "chat_id", None) or state.get("chat_id") or 0)
    if not chat_id:
        return

    # Delete current list message (or any current message we came from).
    if cq.message:
        with suppress(BadRequest):
            await cq.message.delete()

    ingredients_text = "\n".join(f"- {ingredient.name}" for ingredient in (recipe.ingredients or []))
    title_html = escape(recipe.title or "Без названия")
    description_html = escape(recipe.description or "—")
    text = (
        f"🍽 <b>Название рецепта:</b> {title_html}\n\n"
        f"📝 <b>Рецепт:</b>\n{description_html}\n\n"
        f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
    )

    kb = InlineKB()
    if not already_linked:
        kb.button(text="➕ Добавить к себе", callback_data=f"urladd:{sid}:{int(recipe_id)}")
    kb.button(text="⬅️ Назад к списку", callback_data=f"urllist:{sid}")
    kb.button(text="🏠 На главную", callback_data="start")

    header = "Этот рецепт у Вас уже сохранён ✅" if already_linked else "Рецепт из каталога ✅"
    body = f"{header}\n\n{text}"

    # Send video first (if any), then send recipe message.
    video_mid = None
    try:
        video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    except Exception:
        video_url = None
    if video_url:
        with suppress(BadRequest):
            video_msg = await context.bot.send_video(chat_id=chat_id, video=video_url)
            video_mid = int(video_msg.message_id)
            await append_message_id_to_cache(update, context, video_mid)

    recipe_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=body,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=kb.adjust(1),
    )
    await append_message_id_to_cache(update, context, recipe_msg.message_id)

    await _set_state(
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
    cq = update.callback_query
    if not cq or not cq.data or not cq.from_user:
        return
    await cq.answer()
    try:
        _, sid = cq.data.split(":", 1)
    except Exception:
        return

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    state = await _get_state(redis, user_id=user_id, sid=sid)
    if not state:
        await cq.edit_message_text("Список по ссылке устарел. Пришлите ссылку ещё раз.", reply_markup=home_keyboard())
        return

    chat_id = int(getattr(cq.message, "chat_id", None) or state.get("chat_id") or 0)
    if not chat_id:
        return

    # Delete current recipe message (the one with "Back"), and the video message (if present).
    msg_ids_to_delete: list[int] = []
    if cq.message:
        msg_ids_to_delete.append(int(cq.message.message_id))
    if state.get("video_message_id"):
        msg_ids_to_delete.append(int(state["video_message_id"]))
    await _delete_messages(context, chat_id=chat_id, message_ids=msg_ids_to_delete)

    recipe_ids = [int(x) for x in (state.get("recipe_ids") or []) if isinstance(x, int | str) and str(x).isdigit()]
    async with db.session() as session:
        stmt = (
            RecipeRepository.model.__table__.select()
            .with_only_columns(RecipeRepository.model.id, RecipeRepository.model.title)
            .where(RecipeRepository.model.id.in_(recipe_ids))
        )
        rows = (await session.execute(stmt)).all()
        id_to_title = {int(r.id): str(r.title) for r in rows}
        recipe_titles = [(rid, id_to_title.get(int(rid), "")) for rid in recipe_ids if int(rid) in id_to_title]

    kb = InlineKB()
    for rid, title in recipe_titles:
        t = (title or "").strip() or "Без названия"
        if len(t) > 45:
            t = t[:42] + "..."
        kb.button(text=f"▪️ {t}", callback_data=f"urlpick:{sid}:{int(rid)}")
    kb.button(text="🏠 На главную", callback_data="start")

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text="По этой ссылке найдено несколько рецептов. Выберите нужный:",
        reply_markup=kb.adjust(1),
    )
    await append_message_id_to_cache(update, context, sent.message_id)
    await _set_state(
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
    cq = update.callback_query
    if not cq or not cq.data or not cq.from_user:
        return
    await cq.answer()

    try:
        _, sid, recipe_id_str = cq.data.split(":", 2)
        recipe_id = int(recipe_id_str)
    except Exception:
        return

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    state = await _get_state(redis, user_id=user_id, sid=sid)
    if not state:
        await cq.edit_message_text("Список по ссылке устарел. Пришлите ссылку ещё раз.", reply_markup=home_keyboard())
        return

    allowed = {int(x) for x in (state.get("recipe_ids") or []) if isinstance(x, int | str) and str(x).isdigit()}
    if recipe_id not in allowed:
        await cq.edit_message_text("Этот рецепт больше недоступен в списке.", reply_markup=home_keyboard())
        return

    service = CategoryService(db, redis)
    categories = await service.get_all_category()
    kb = InlineKB()
    for cat in categories:
        name = str(cat.get("name") or "").strip()
        slug = str(cat.get("slug") or "").strip().lower()
        if not name or not slug:
            continue
        kb.button(text=name, callback_data=f"urladdcat:{sid}:{int(recipe_id)}:{slug}")
    kb.button(text="⬅️ Назад к списку", callback_data=f"urllist:{sid}")
    kb.button(text="🏠 На главную", callback_data="start")

    await cq.edit_message_text("Выберите категорию для добавления рецепта:", reply_markup=kb.adjust(1))


async def add_candidate_recipe_choose_category(update: Update, context: PTBContext) -> None:
    """
    Entry-point: r"^urladdcat:[A-Za-z0-9]+:\\d+:[a-z0-9_-]+$"
    """
    cq = update.callback_query
    if not cq or not cq.data or not cq.from_user:
        return
    await cq.answer()

    try:
        _, sid, recipe_id_str, slug = cq.data.split(":", 3)
        recipe_id = int(recipe_id_str)
    except Exception:
        return

    user_id = int(cq.from_user.id)
    db, redis = get_db_and_redis(context)
    service = CategoryService(db, redis)
    category_id, _ = await service.get_id_and_name_by_slug_cached(slug)

    message_text = "✅ Рецепт успешно сохранён."
    async with db.session() as session:
        if await RecipeUserRepository.is_linked(session, recipe_id, user_id):
            message_text = "ℹ️ Рецепт уже есть у вас, обновили категорию."
            await RecipeRepository.update_category(session, recipe_id, user_id, category_id)
        else:
            await RecipeUserRepository.link_user(session, recipe_id, user_id, category_id)
        await session.commit()

    await CategoryCacheRepository.invalidate_user_categories(redis, user_id)
    await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(redis, user_id, category_id)

    # Пользователь уже выбрал рецепт и категорию. К списку по ссылке возвращаться не нужно.
    # Заодно подчистим состояние выбора по ссылке.
    await RecipeActionCacheRepository.delete(redis, user_id, _action_key(sid))

    await cq.edit_message_text(message_text, reply_markup=home_keyboard())
