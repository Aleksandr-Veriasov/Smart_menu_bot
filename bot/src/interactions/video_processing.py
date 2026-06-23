import asyncio
import logging

from aiogram import Bot
from aiogram.types import Message, User

from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.pipeline_drafts import PipelineDraftStore
from bot.src.bot_ui.url_candidates import UrlCandidateStore
from bot.src.interactions.existing_recipe import show_existing_recipe_if_found
from bot.src.interactions.video_pipeline import process_video_pipeline
from packages.redis.data_models import PipelineDraft
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)

# Фоновые задачи пайплайна. Держим ссылки, чтобы их не собрал GC.
_background_tasks: set[asyncio.Task] = set()


def build_pipeline_id(message: Message) -> int:
    """Строит уникальный pipeline_id на основе chat_id и message_id."""
    return int(f"{abs(message.chat.id)}{message.message_id:010d}")


async def start_video_processing(
    message: Message,
    user: User,
    *,
    bot: Bot,
    recipe_service: RecipeService,
    message_service: MessageService,
    pipeline_draft_store: PipelineDraftStore,
    url_candidate_store: UrlCandidateStore,
    url: str,
) -> None:
    """Проверяет существующие рецепты и запускает фоновый pipeline обработки видео."""
    if await show_existing_recipe_if_found(message, recipe_service, message_service, url_candidate_store, url):
        return

    pipeline_id = build_pipeline_id(message)
    await pipeline_draft_store.set(
        pipeline_id,
        PipelineDraft(status="started", original_url=url),
    )

    logger.debug("Пользователь отправил ссылку: %s, pipeline_id=%s", url, pipeline_id)
    task = asyncio.create_task(
        process_video_pipeline(
            url,
            message,
            bot=bot,
            recipe_service=recipe_service,
            redis=pipeline_draft_store.redis,
            pipeline_id=pipeline_id,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
