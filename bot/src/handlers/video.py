import asyncio
import logging
import re

from aiogram import Bot, Router
from aiogram.enums import MessageEntityType
from aiogram.filters import BaseFilter
from aiogram.types import Message
from redis.asyncio import Redis

from bot.src.handlers.recipes.check_existing_recipe import handle_existing_recipe
from bot.src.services.video_pipeline import process_video_pipeline
from bot.src.utils.messaging import answer_and_track
from packages.redis.data_models import PipelineDraft
from packages.redis.repository import PipelineDraftCacheRepository
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

router = Router(name="video")

_URL_RE = re.compile(r"(?P<url>https?://(?:www\.)?[^\s<>()\[\]]+)", re.IGNORECASE)

VIDEO_LINK_PATTERN = (
    r"(https?://)?(www\.)?"
    r"("
    r"youtube\.com|youtu\.be|youtube\.com/shorts|tiktok\.com|vm\.tiktok\.com|"
    r"instagram\.com|pinterest\.com|pin\.it|pinterest\.co"
    r")/\S+"
)
_VIDEO_LINK_RE = re.compile(VIDEO_LINK_PATTERN)

# Фоновые задачи пайплайна. Держим ссылки, чтобы их не собрал GC.
_background_tasks: set[asyncio.Task] = set()


class VideoLinkFilter(BaseFilter):
    """Пропускает только текстовые сообщения, содержащие ссылку на поддерживаемое видео."""

    async def __call__(self, message: Message) -> bool:
        text = message.text or ""
        return bool(text) and bool(_VIDEO_LINK_RE.search(text))


def extract_first_url(message: Message) -> str | None:
    """Вернёт первую ссылку из текста/подписи сообщения, если она есть."""
    # 1) Сначала — entities (Telegram сам корректно выделяет URL и TEXT_LINK)
    for entities, source_text in (
        (message.entities, message.text),
        (message.caption_entities, message.caption),
    ):
        if not entities or not source_text:
            continue
        for ent in entities:
            if ent.type == MessageEntityType.TEXT_LINK and ent.url:
                return ent.url
            if ent.type == MessageEntityType.URL:
                return ent.extract_from(source_text)

    # 2) Fallback — простая регулярка по тексту/подписи
    s = message.text or message.caption or ""
    m = _URL_RE.search(s)
    return m.group("url").rstrip(".,);:!?]»”") if m else None


@router.message(VideoLinkFilter())
async def video_link(
    message: Message,
    bot: Bot,
    recipe_service: RecipeService,
    redis: Redis,
) -> None:
    """Принимает сообщение со ссылкой и запускает обработку видео."""
    url = extract_first_url(message)
    if not url:
        await answer_and_track(message, redis, "❌ Не нашёл ссылку в сообщении. Пришлите корректный URL.")
        return

    if await handle_existing_recipe(message, recipe_service, redis, url):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в video_link")
        return
    # Уникальный pipeline_id на основе (chat_id, message_id) через конкатенацию
    pipeline_id = int(f"{abs(chat_id)}{message.message_id:010d}")

    await PipelineDraftCacheRepository.set(
        redis,
        user_id,
        pipeline_id,
        PipelineDraft(status="started", original_url=url),
    )

    logger.debug(f"Пользователь отправил ссылку: {url}, pipeline_id={pipeline_id}")
    task = asyncio.create_task(
        process_video_pipeline(
            url,
            message,
            bot=bot,
            recipe_service=recipe_service,
            redis=redis,
            pipeline_id=pipeline_id,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
