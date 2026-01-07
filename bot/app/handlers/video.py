import logging
import re

from telegram import Message, MessageEntity, Update

from bot.app.core.types import PTBContext
from bot.app.handlers.recipes.check_existing_recipe import handle_existing_recipe
from bot.app.services.video_pipeline import process_video_pipeline

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"(?P<url>https?://(?:www\.)?[^\s<>()\[\]]+)", re.IGNORECASE)


def extract_first_url(msg: Message) -> str | None:
    """Вернёт первую ссылку из текста/подписи сообщения, если она есть."""
    # 1) Сначала — entities (Telegram сам корректно выделяет URL и TEXT_LINK)
    ent_map = msg.parse_entities([MessageEntity.URL, MessageEntity.TEXT_LINK]) or {}
    for ent, value in ent_map.items():
        if ent.type == MessageEntity.TEXT_LINK and ent.url:
            return ent.url
        if ent.type == MessageEntity.URL:
            return value

    # 2) Затем — caption_entities (если ссылка в подписи к медиа)
    cap_map = msg.parse_caption_entities([MessageEntity.URL, MessageEntity.TEXT_LINK]) or {}
    for ent, value in cap_map.items():
        if ent.type == MessageEntity.TEXT_LINK and ent.url:
            return ent.url
        if ent.type == MessageEntity.URL:
            return value

    # 3) Fallback — простая регулярка по тексту/подписи
    s = msg.text or msg.caption or ""
    m = _URL_RE.search(s)
    return m.group("url").rstrip(".,);:!?]»”") if m else None


async def video_link(update: Update, context: PTBContext) -> None:
    """
    Принимает сообщение с ссылкой и запускает обработку.
    Entry-point: /video_link
    """
    message = update.effective_message
    if not message:
        return
    url = extract_first_url(message)
    if not url:
        await message.reply_text("❌ Не нашёл ссылку в сообщении. Пришлите корректный URL.")
        return

    if await handle_existing_recipe(message, context, url):
        return

    chat_id = message.chat_id
    # Уникальный pipeline_id на основе (chat_id, message_id) через конкатенацию
    pipeline_id = int(f"{abs(chat_id)}{message.message_id:010d}")

    # Можем пометить, что пайплайн запущен
    pipelines = context.user_data.setdefault("pipelines", {}) if context.user_data else {}
    pipelines[pipeline_id] = {"status": "started", "original_url": url}

    logger.debug(f"Пользователь отправил ссылку: {url}, pipeline_id={pipeline_id}")
    context.application.create_task(process_video_pipeline(url, message, context, pipeline_id=pipeline_id))
