from aiogram import Bot, Router
from aiogram.types import Message
from redis.asyncio import Redis

from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.pipeline_drafts import PipelineDraftStore
from bot.src.bot_ui.url_candidates import UrlCandidateStore
from bot.src.filters.video import VideoLinkFilter
from bot.src.interactions.video_processing import start_video_processing
from bot.src.utils.url import extract_first_url
from packages.services.recipe_service import RecipeService

router = Router(name="video")


@router.message(VideoLinkFilter())
async def video_link(
    message: Message,
    bot: Bot,
    redis: Redis,
    recipe_service: RecipeService,
    message_service: MessageService,
    pipeline_draft_store: PipelineDraftStore,
    url_candidate_store: UrlCandidateStore,
) -> None:
    """Принимает сообщение со ссылкой и запускает обработку видео."""
    url = extract_first_url(message)
    if not url:
        await message_service.answer_and_track(message, "❌ Не нашёл ссылку в сообщении. Пришлите корректный URL.")
        return

    await start_video_processing(
        message,
        bot=bot,
        redis=redis,
        recipe_service=recipe_service,
        message_service=message_service,
        pipeline_draft_store=pipeline_draft_store,
        url_candidate_store=url_candidate_store,
        url=url,
    )
