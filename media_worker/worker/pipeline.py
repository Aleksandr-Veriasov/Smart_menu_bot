"""Конвейер обработки видео для media_worker.

- нотификации через MediaWorkerNotifier (plain HTTP)
- draft пишется в Redis чтобы bot-обработчик Save смог найти recipe_id
- upload видео в канал идёт параллельно с транскрибацией
"""

import asyncio
import logging
from pathlib import Path

from redis.asyncio import Redis

from media_worker.notifications.notifier import MediaWorkerNotifier
from media_worker.transcription.whisper_model import transcribe_async
from packages.db.models.pipeline import PipelineJob
from packages.media.audio_extractor import async_extract_audio
from packages.media.safe_remove import safe_remove
from packages.media.video_converter import async_convert_to_mp4
from packages.media.video_downloader import async_download_video_and_description
from packages.recipes_core.services.provider import get_default_extractor
from packages.redis.data_models import PipelineDraft
from packages.redis.repository.message_ids import UserMessageIdsCacheRepository
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

    async def _progress(pct: int, label: str) -> None:
        if msg_id is not None:
            await notifier.edit_progress(chat_id, msg_id, pct, label)

    try:
        # 1. Скачиваем видео (бросает FatalPipelineError если контент недоступен)
        video_path, description = await async_download_video_and_description(job.url)
        await _progress(20, "Видео скачано")

        # 2. Переименовываем чтобы избежать коллизий между jobs
        suffixed = _with_pipeline_suffix(video_path, job_id)
        try:
            Path(video_path).rename(suffixed)
            video_path = suffixed
        except Exception as exc:
            logger.warning("Не удалось переименовать %s → %s: %s", video_path, suffixed, exc)

        # 3. Конвертируем в mp4
        converted_path = await async_convert_to_mp4(video_path)
        safe_remove(video_path)
        await _progress(40, "Видео конвертировано")

        # 4. Запускаем upload в канал параллельно с извлечением аудио и транскрибацией
        upload_task: asyncio.Task[str] = asyncio.create_task(notifier.upload_video_to_channel(converted_path))

        # 5. Извлекаем аудио
        audio_path = await async_extract_audio(converted_path, AUDIO_FOLDER)
        if not audio_path:
            upload_task.cancel()
            raise RuntimeError("Не удалось извлечь аудио из видео")
        await _progress(55, "Аудио извлечено")

        # 6. Транскрибируем
        transcript = await transcribe_async(audio_path)
        safe_remove(audio_path)
        await _progress(70, "Речь распознана")

        # 7. Извлекаем рецепт через AI
        extractor = get_default_extractor()
        result = await extractor.extract(description=description, recognized_text=transcript)
        title, recipe, ingredients = result.title, result.instructions_text, result.ingredients_text
        await _progress(85, "Рецепт готов")

        if not title or not recipe:
            upload_task.cancel()
            raise RuntimeError("AI не смог извлечь рецепт из видео")

        # Получаем file_id из upload (если успел — мгновенно, иначе ждём)
        try:
            video_file_id: str = await upload_task
        except Exception:
            logger.warning("job_id=%s upload в канал не удался, продолжаем без file_id", job_id)
            video_file_id = ""

        if video_file_id:
            safe_remove(converted_path)

        # 8. Сохраняем черновик рецепта в БД
        recipe_id = await recipe_service.save_recipe_draft(
            title=title,
            description=recipe,
            ingredients=ingredients,
            original_url=job.url,
            video_url=video_file_id or None,
        )

        # 9. Кладём draft в Redis — bot-обработчик save читает оттуда
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

        # 10. Удаляем прогресс-сообщение перед финальными сообщениями
        if msg_id is not None:
            await notifier.delete_message(chat_id, msg_id)

        # 12. Отправляем видео и карточку пользователю, трекаем message_id
        sent_ids: list[int] = []

        if video_file_id:
            video_msg_id = await notifier.send_video_to_user(chat_id, video_file_id)
            if video_msg_id:
                sent_ids.append(video_msg_id)

        recipe_msg_id = await notifier.send_recipe_card(
            chat_id,
            title=title,
            recipe=recipe,
            ingredients=ingredients if isinstance(ingredients, list) else [ingredients],
            pipeline_id=job_id,
        )
        if recipe_msg_id:
            sent_ids.append(recipe_msg_id)

        if sent_ids:
            await UserMessageIdsCacheRepository(redis).set_user_message_ids(
                user_id, chat_id=chat_id, message_ids=sent_ids
            )

        if not video_file_id:
            safe_remove(converted_path)

    except Exception as exc:
        logger.exception("job_id=%s failed", job.id)
        await notifier.send_error(chat_id, msg_id, str(exc))
        raise
