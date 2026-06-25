import logging

from aiogram.types import Message

from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.pipeline_drafts import PipelineDraftStore
from bot.src.bot_ui.url_candidates import UrlCandidateStore
from bot.src.interactions.existing_recipe import show_existing_recipe_if_found
from packages.db.repository import PipelineJobRepository
from packages.redis.data_models import PipelineDraft
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)


async def start_video_processing(
    message: Message,
    *,
    user_id: int,
    recipe_service: RecipeService,
    message_service: MessageService,
    pipeline_draft_store: PipelineDraftStore,
    url_candidate_store: UrlCandidateStore,
    url: str,
) -> None:
    if await show_existing_recipe_if_found(message, recipe_service, message_service, url_candidate_store, url):
        return

    async with recipe_service.db.session() as session:
        repo = PipelineJobRepository(session)
        job = await repo.enqueue(
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=user_id,
            url=url,
        )
        await pipeline_draft_store.set(
            job.id,
            PipelineDraft(status="queued", original_url=url),
        )
        progress_msg = await message.answer("🔄 Обрабатываю видео, это займёт около минуты…")
        if progress_msg:
            await repo.set_progress_message_id(job.id, progress_msg.message_id)

    logger.info("job_id=%s поставлен в очередь (user_id=%s)", job.id, user_id)
