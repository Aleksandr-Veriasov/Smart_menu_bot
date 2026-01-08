import base64
import hashlib
import logging
import os
from html import escape

from telegram import Update
from telegram.constants import ParseMode

from bot.app.core.types import AppState, PTBContext
from bot.app.keyboards.inlines import add_recipe_keyboard, home_keyboard
from bot.app.utils.context_helpers import get_db
from bot.app.utils.message_cache import append_message_id_to_cache
from packages.common_settings.settings import settings
from packages.db.repository import RecipeRepository, VideoRepository
from packages.redis.repository import RecipeMessageCacheRepository

logger = logging.getLogger(__name__)

_NONCE_LEN = 8


def _pepper_bytes() -> bytes:
    """Возвращает секретный ключ (pepper) в байтах."""
    pepper = settings.security.password_pepper
    if not pepper:
        raise RuntimeError("PASSWORD_PEPPER не задан")
    return pepper.get_secret_value().encode("utf-8")


def _keystream(pepper: bytes, nonce: bytes, length: int) -> bytes:
    """Генерирует поток ключей для шифрования/дешифрования."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        counter_bytes = counter.to_bytes(4, "big", signed=False)
        block = hashlib.sha256(pepper + nonce + counter_bytes).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _encrypt_recipe_id(recipe_id: str) -> str:
    """Шифрует recipe_id в токен для шаринга."""
    pepper = _pepper_bytes()
    nonce = os.urandom(_NONCE_LEN)
    plaintext = recipe_id.encode("utf-8")
    stream = _keystream(pepper, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream, strict=False))
    token = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    return token


def _decrypt_recipe_id(token: str) -> str | None:
    """Дешифрует токен и возвращает recipe_id или None, если не удалось."""
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding)
        if len(raw) <= _NONCE_LEN:
            return None
        nonce = raw[:_NONCE_LEN]
        ciphertext = raw[_NONCE_LEN:]
        pepper = _pepper_bytes()
        stream = _keystream(pepper, nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream, strict=False))
        return plaintext.decode("utf-8").strip()
    except Exception:
        return None


async def build_recipe_share_link(
    context: PTBContext,
    recipe_id: str,
    *,
    payload_prefix: str = "share",
) -> str:
    """
    Собирает deep-link для шаринга рецепта через параметр start.
    Пример: https://t.me/<bot>?start=share_<slug>
    """
    recipe_id_str = str(recipe_id).strip()
    if not recipe_id_str:
        raise ValueError("recipe_id пустой")

    token = _encrypt_recipe_id(recipe_id_str)
    payload = f"{payload_prefix}_{token}"

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
    Entry-point: r"^share_recipe_\\d+$""
    """
    cq = update.callback_query
    if not cq:
        return

    await cq.answer()
    data = cq.data or ""
    recipe_id = data.split("_")[-1]
    if not recipe_id:
        raise ValueError("recipe_id пустой")

    url = await build_recipe_share_link(context, recipe_id)
    title_html = "Рецепт"
    desc_html = "—"
    db = get_db(context)
    async with db.session() as session:
        recipe = await RecipeRepository.get_by_id(session, int(recipe_id))
        if recipe and recipe.title:
            title_html = escape(recipe.title)
        if recipe and recipe.description:
            desc_raw = recipe.description.strip()
            if len(desc_raw) > 150:
                desc_raw = f"{desc_raw[:147]}..."
            desc_html = escape(desc_raw) if desc_raw else "—"
    msg = update.effective_message
    if msg:
        text_msg = await msg.reply_text(
            f"🍽 <b>Название рецепта:</b> {title_html}\n\n" f"📝 <b>Рецепт:</b>\n{desc_html}\n\n" f"Весь рецепт: {url}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=home_keyboard(),
        )
        app_state = context.bot_data.get("state")
        if isinstance(app_state, AppState) and app_state.redis is not None and update.effective_chat and cq.from_user:
            await RecipeMessageCacheRepository.append_user_message_ids(
                app_state.redis,
                cq.from_user.id,
                update.effective_chat.id,
                [text_msg.message_id],
            )


async def handle_shared_start(update: Update, context: PTBContext, token: str) -> bool:
    """Обрабатывает старт с шаренной ссылкой рецепта."""
    recipe_id = _decrypt_recipe_id(token)
    if not recipe_id or not recipe_id.isdigit():
        return False

    db = get_db(context)
    async with db.session() as session:
        recipe = await RecipeRepository.get_by_id(session, int(recipe_id))
        if not recipe:
            return False
        video_url = await VideoRepository.get_video_url(session, int(recipe.id))
        ingredients_text = "\n".join(f"- {ingredient.name}" for ingredient in recipe.ingredients)
        title_html = escape(recipe.title or "Без названия")
        description_html = escape(recipe.description or "—")
        text = (
            f"🍽 <b>Название рецепта:</b> {title_html}\n\n"
            f"📝 <b>Рецепт:</b>\n{description_html}\n\n"
            f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
        )

    msg = update.effective_message
    if msg:
        if video_url:
            video_msg = await msg.reply_video(video_url)
            await append_message_id_to_cache(update, context, video_msg.message_id)
        reply = await msg.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=add_recipe_keyboard(int(recipe_id)),
        )
        await append_message_id_to_cache(update, context, reply.message_id)

    return True
