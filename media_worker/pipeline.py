"""Конвейер обработки видео для media_worker.

Адаптация bot/src/interactions/video_pipeline.py для изолированного процесса:
- нет aiogram / Bot / Message
- нет Redis-кэша progress (message_id приходит из pipeline_jobs)
- нет аплоада видео в канал (video_file_id=None, Sprint 0)
- нотификации через MediaWorkerNotifier (plain HTTP)
- draft пишется в Redis чтобы bot-обработчик Save смог найти recipe_id
"""

import asyncio
import logging
from pathlib import Path

from redis.asyncio import Redis

from media_worker.notifier import MediaWorkerNotifier
from media_worker.whisper_model import transcribe_async
from packages.db.models.pipeline import PipelineJob
from packages.media.audio_extractor import extract_audio
from packages.media.safe_remove import safe_remove
from packages.media.video_converter import convert_to_mp4
from packages.media.video_downloader import download_video_and_description
from packages.recipes_core.services.provider import get_default_extractor
from packages.redis.data_models import PipelineDraft
from packages.redis.repository.pipeline_draft import PipelineDraftCacheRepository
from packages.services.recipe_service import RecipeService

AUDIO_FOLDER = "audio/"

logger = logging.getLogger(__name__)


def _with_pipeline_suffix(path: str, pipeline_id: int) -> str:
    p = Path(path)
    if not p.suffix:
        return f"{path}_{pipeline_id}"
    return str(p.with_name(f"{p.stem}_{pipeline_id}{p.suffix}"))


async def run(
    job: PipelineJob,
    *,
    recipe_service: RecipeService,
    redis: Redis,
    notifier: MediaWorkerNotifier,
) -> None:
    """Выполнить один job: скачать → транскрибировать → сохранить черновик → уведомить."""
    chat_id = job.chat_id
    user_id = job.user_id
    job_id = job.id
    msg_id = job.progress_message_id

    def _progress(pct: int, label: str) -> None:
        if msg_id is not None:
            notifier.edit_progress(chat_id, msg_id, pct, label)

    try:
        # 1. Скачиваем видео
        video_path, description = await asyncio.to_thread(download_video_and_description, job.url)
        if not video_path:
            raise RuntimeError("Не удалось скачать видео")
        _progress(20, "Видео скачано")

        # 2. Переименовываем чтобы избежать коллизий между jobs
        suffixed = _with_pipeline_suffix(video_path, job_id)
        try:
            Path(video_path).rename(suffixed)
            video_path = suffixed
        except Exception as exc:
            logger.warning("Не удалось переименовать %s → %s: %s", video_path, suffixed, exc)

        # 3. Конвертируем в mp4
        converted_path = await asyncio.to_thread(convert_to_mp4, video_path)
        safe_remove(video_path)
        _progress(40, "Видео конвертировано")

        # 4. Извлекаем аудио
        audio_path = await asyncio.to_thread(extract_audio, converted_path, AUDIO_FOLDER)
        if not audio_path:
            raise RuntimeError("Не удалось извлечь аудио из видео")
        _progress(55, "Аудио извлечено")

        # 5. Транскрибируем
        transcript = await transcribe_async(audio_path)
        safe_remove(audio_path)
        _progress(70, "Речь распознана")

        # 6. Извлекаем рецепт через AI
        extractor = get_default_extractor()
        result = await extractor.extract(description=description, recognized_text=transcript)
        title, recipe, ingredients = result.title, result.instructions_text, result.ingredients_text
        _progress(85, "Рецепт готов")

        if not title or not recipe:
            raise RuntimeError("AI не смог извлечь рецепт из видео")

        # 7. Сохраняем черновик рецепта в БД
        recipe_id = await recipe_service.save_recipe_draft(
            title=title,
            description=recipe,
            ingredients=ingredients,
            original_url=job.url,
        )

        # 8. Кладём draft в Redis — bot-обработчик save читает оттуда
        draft_repo = PipelineDraftCacheRepository(redis)
        await draft_repo.set(
            user_id,
            job_id,
            PipelineDraft(
                original_url=job.url,
                title=title,
                recipe=recipe,
                ingredients=ingredients,
                recipe_id=recipe_id,
            ),
        )

        # 9. Отправляем карточку рецепта пользователю
        notifier.send_recipe_card(
            chat_id,
            title=title,
            recipe=recipe,
            ingredients=ingredients if isinstance(ingredients, list) else [ingredients],
            pipeline_id=job_id,
        )
        _progress(100, "Готово ✅")

        safe_remove(converted_path)

    except Exception as exc:
        logger.exception("job_id=%s failed", job.id)
        notifier.send_error(chat_id, msg_id, str(exc))
        raise
