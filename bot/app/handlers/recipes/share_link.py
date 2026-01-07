import base64
import hashlib
import logging

from telegram import Update

from bot.app.core.types import PTBContext
from packages.common_settings.settings import settings

logger = logging.getLogger(__name__)

_SLUG_LENGTH = 10


def _share_slug(recipe_id: str) -> str:
    pepper = settings.security.password_pepper
    pepper_value = pepper.get_secret_value() if pepper else ""
    material = f"{recipe_id}:{pepper_value}".encode()
    digest = hashlib.sha256(material).digest()
    slug = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return slug[:_SLUG_LENGTH]


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

    slug = _share_slug(recipe_id_str)
    payload = f"{payload_prefix}_{slug}"

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
    cq = update.callback_query
    if not cq:
        return

    await cq.answer()
    data = cq.data or ""
    recipe_id = data.split("_")[-1]
    if not recipe_id:
        raise ValueError("recipe_id пустой")

    url = await build_recipe_share_link(context, recipe_id)
    if cq.message:
        await cq.message.reply_text(url)
