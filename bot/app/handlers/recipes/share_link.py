import logging
from html import escape

from telegram import Update
from telegram.constants import ParseMode

from bot.app.core.data_models import RecipesStateData
from bot.app.core.recipes_mode import RecipeMode
from bot.app.core.types import PTBContext
from bot.app.keyboards.callbacks import RecipeCallbacks, SharedCallbacks
from bot.app.keyboards.inlines import (
    add_recipe_keyboard,
    choice_recipe_keyboard,
    home_keyboard,
    share_recipe_keyboard,
)
from bot.app.utils.callback_utils import get_answered_callback_query
from bot.app.utils.context_helpers import get_db, get_db_and_redis, get_redis_cli
from bot.app.utils.message_cache import (
    delete_all_user_messages,
    reply_text_and_cache,
    reply_video_and_cache,
)
from bot.app.utils.message_utils import build_existing_recipe_text
from bot.app.utils.share_token import decrypt_recipe_id, encrypt_recipe_id
from packages.db.repository import RecipeRepository
from packages.redis.repository import RecipeActionCacheRepository

logger = logging.getLogger(__name__)


async def build_recipe_share_link(
    context: PTBContext,
    recipe_id: int | str,
    *,
    payload_prefix: str = "share",
) -> str:
    """
    Собирает deep-link для шаринга рецепта через параметр start.
    Пример: https://t.me/<bot>?start=share:<token>
    """
    recipe_id_str = str(recipe_id).strip()
    if not recipe_id_str:
        logger.error("Пустой recipe_id при формировании ссылки для шаринга")
        raise ValueError("recipe_id пустой")

    token = encrypt_recipe_id(recipe_id_str)
    payload = (
        SharedCallbacks.build_shared_start_payload(token) if payload_prefix == "share" else f"{payload_prefix}_{token}"
    )

    username = context.bot.username
    if not username:
        me = await context.bot.get_me()
        username = me.username if me.username else ""

    if not username:
        raise RuntimeError("Username бота пустой")

    url = f"https://t.me/{username.lstrip('@')}?start={payload}"
    logger.info("Сформирована ссылка для шаринга рецепта: %s", url)
    return url


async def share_recipe_link_handler(update: Update, context: PTBContext) -> None:
    """
    Хэндлер для обработки нажатия кнопки шаринга рецепта.
    Entry-point: callback `recipe:share:<recipe_id>`.
    """
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.data:
        return
    recipe_id = RecipeCallbacks.parse_recipe_share(cq.data)
    if recipe_id is None:
        raise ValueError("recipe_id пустой")

    url = await build_recipe_share_link(context, recipe_id)
    db = get_db(context)
    async with db.session() as session:
        recipe = await RecipeRepository.get_by_id(session, int(recipe_id))
    title_html = escape(recipe.title) if recipe and recipe.title else "Рецепт"
    desc_html = "—"
    if recipe and recipe.description:
        desc_raw = recipe.description.strip()
        if len(desc_raw) > 150:
            desc_raw = f"{desc_raw[:147]}..."
        desc_html = escape(desc_raw) if desc_raw else "—"
    msg = update.effective_message
    if msg:
        user_id = update.effective_user.id if update.effective_user else None
        redis = get_redis_cli(context)
        if user_id and redis is not None:
            await delete_all_user_messages(context, redis, user_id, msg.chat_id)
        await reply_text_and_cache(
            msg,
            context,
            f"🍽 <b>Название рецепта:</b> {title_html}\n\n" f"📝 <b>Рецепт:</b>\n{desc_html}\n\n" f"Весь рецепт: {url}",
            user_id=user_id,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=share_recipe_keyboard(recipe_id),
        )


async def share_recipe_back_handler(update: Update, context: PTBContext) -> None:
    """Возвращает пользователя из шаринга к карточке рецепта."""
    cq = await get_answered_callback_query(update, require_data=True)
    if not cq or not cq.data:
        return

    recipe_id = RecipeCallbacks.parse_share_back(cq.data)
    if recipe_id is None:
        return
    user_id = update.effective_user.id if update.effective_user else None
    msg = update.effective_message
    if not user_id or not msg:
        return

    db, redis = get_db_and_redis(context)
    await delete_all_user_messages(context, redis, user_id, msg.chat_id)

    state = RecipesStateData.from_dict(await RecipeActionCacheRepository.get(redis, user_id, "recipes_state"))
    category_slug = state.category_slug
    mode_value = RecipeMode.SHOW.value if state.mode == RecipeMode.SEARCH.value else state.mode

    keyboard = choice_recipe_keyboard(
        recipe_id,
        state.recipes_page,
        category_slug,
        mode_value,
        add_to_self=SharedCallbacks.is_book_slug(category_slug),
        can_manage=mode_value == RecipeMode.SHOW.value and not SharedCallbacks.is_book_slug(category_slug),
    )

    async with db.session() as session:
        recipe = await RecipeRepository.get_recipe_with_connections(session, recipe_id)
        if recipe:
            await RecipeRepository.update_last_used_at(session, int(recipe.id))

    if not recipe:
        await reply_text_and_cache(
            msg,
            context,
            "❌ Рецепт не найден.",
            user_id=user_id,
            reply_markup=home_keyboard(),
        )
        return

    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    text = build_existing_recipe_text(recipe)
    if video_url:
        await reply_video_and_cache(msg, context, video_url, user_id=user_id)
    await reply_text_and_cache(
        msg,
        context,
        text,
        user_id=user_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
    )


async def handle_shared_start(update: Update, context: PTBContext, token: str) -> bool:
    """Обрабатывает старт с шаренной ссылкой рецепта."""
    recipe_id = decrypt_recipe_id(token)
    if not recipe_id or not recipe_id.isdigit():
        return False

    db = get_db(context)
    async with db.session() as session:
        recipe = await RecipeRepository.get_recipe_with_connections(session, int(recipe_id))
        if not recipe:
            return False
    video_url = getattr(getattr(recipe, "video", None), "video_url", None)
    text = build_existing_recipe_text(recipe)

    msg = update.effective_message
    if msg:
        user_id = update.effective_user.id if update.effective_user else None
        if video_url:
            await reply_video_and_cache(msg, context, video_url, user_id=user_id)
        await reply_text_and_cache(
            msg,
            context,
            text,
            user_id=user_id,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=add_recipe_keyboard(int(recipe_id)),
        )

    return True
