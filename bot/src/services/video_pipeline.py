import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message
from redis.asyncio import Redis

from bot.src.messages.recipe_confirmation import send_recipe_confirmation
from bot.src.messages.telegram_media import send_video_to_channel
from bot.src.notifications.telegram_notifier import TelegramNotifier
from bot.src.utils.deepseek_answers import extract_recipes
from packages.media.audio_extractor import extract_audio
from packages.media.safe_remove import safe_remove
from packages.media.speech_recognition import async_transcribe_audio
from packages.media.video_converter import async_convert_to_mp4
from packages.media.video_downloader import async_download_video_and_description
from packages.services.recipe_service import RecipeService

AUDIO_FOLDER = "audio/"

logger = logging.getLogger(__name__)


def _with_pipeline_suffix(path: str, pipeline_id: int) -> str:
    p = Path(path)
    if not p.suffix:
        return f"{path}_{pipeline_id}"
    return str(p.with_name(f"{p.stem}_{pipeline_id}{p.suffix}"))


async def process_video_pipeline(
    url: str,
    message: Message,
    *,
    bot: Bot,
    recipe_service: RecipeService,
    redis: Redis,
    pipeline_id: int,
) -> None:
    """Основной конвейер обработки видео:
    1) Скачиваем видео и описание
    2) Конвертируем в mp4
    3) Загружаем в канал и получаем file_id
    4) Извлекаем аудио
    5) Распознаём текст
    6) Генерируем рецепт через AI
    7) Отправляем пользователю на подтверждение и сохраняем рецепт
    8) (в save_recipe_handler) привязываем рецепт к пользователю и категории
    В случае ошибок — уведомляем пользователя.
    9) Чистим временные файлы
    """
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        logger.error("Не удалось получить user_id в process_video_pipeline")
        return

    notifier = TelegramNotifier(bot, chat_id, redis=redis, source_message=message)
    notifier.message_id = None
    try:
        # стартовое сообщение (создастся и запомнится message_id)
        await notifier.info("🔄 Скачиваю видео и описание... Пожалуйста, подождите.")

        # дальше обычный ход
        video_path, description = await async_download_video_and_description(url)
        await notifier.progress(20, "📼 Видео скачано")
        if not video_path:
            await notifier.error("Не удалось скачать видео. Отправьте ссылку ещё раз.")
            return
        logger.debug(f"Описание скачанного видео: {description}")
        original_path = video_path
        video_path_with_suffix = _with_pipeline_suffix(video_path, pipeline_id)
        try:
            Path(video_path).rename(video_path_with_suffix)
            video_path = video_path_with_suffix
        except Exception as exc:
            logger.warning(
                "Не удалось переименовать видео %s -> %s: %s",
                original_path,
                video_path_with_suffix,
                exc,
            )
        convert_task = asyncio.create_task(async_convert_to_mp4(video_path))
        await notifier.progress(40, "Видео конвертировано")

        def _cleanup_src_video_after_convert(t: asyncio.Task) -> None:
            safe_remove(video_path)

        convert_task.add_done_callback(_cleanup_src_video_after_convert)
        converted_path = await convert_task

        upload_task: asyncio.Task[str | None] = asyncio.create_task(send_video_to_channel(bot, converted_path))
        await notifier.progress(60, "✅ Видео загружено. Распознаём текст...")

        audio_path = extract_audio(converted_path, AUDIO_FOLDER)
        if audio_path:
            transcribe_task = asyncio.create_task(async_transcribe_audio(audio_path))

            def _cleanup_audio_after_done(_task: asyncio.Task) -> None:
                safe_remove(audio_path)

            transcribe_task.add_done_callback(_cleanup_audio_after_done)
            transcript = await transcribe_task
        else:
            await notifier.error("Видео скачалось без аудио. Попробуйте еще раз.")
            return

        await notifier.progress(80, "🧠 Подготавливаем рецепт через AI... " "Рецепт практически готов!")

        title, recipe, ingredients = await extract_recipes(description, transcript)

        video_file_id: str | None = None
        try:
            # если аплоад уже успел — получим результат мгновенно
            video_file_id = await upload_task
        except Exception:
            # не валим весь процесс: просто не будет превью из канала
            video_file_id = None

        if video_file_id:
            safe_remove(converted_path)

        if title and recipe and video_file_id:
            await notifier.progress(100, "Готово ✅")
            await send_recipe_confirmation(
                message,
                recipe_service=recipe_service,
                redis=redis,
                title=title,
                recipe=recipe,
                ingredients=ingredients,
                video_file_id=video_file_id,
                pipeline_id=pipeline_id,
            )
        else:
            await notifier.error("Не удалось извлечь данные из видео.")
    finally:
        await notifier.finalize()
