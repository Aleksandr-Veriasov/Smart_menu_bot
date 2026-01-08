import asyncio
import logging
from pathlib import Path

from telegram import Message

from bot.app.core.types import PTBContext
from bot.app.messages.recipe_confirmation import send_recipe_confirmation
from bot.app.messages.telegram_media import send_video_to_channel
from bot.app.notifications.telegram_notifier import TelegramNotifier
from bot.app.utils.deepseek_answers import extract_recipes
from packages.media.audio_extractor import extract_audio
from packages.media.safe_remove import safe_remove
from packages.media.speech_recognition import async_transcribe_audio
from packages.media.video_converter import async_convert_to_mp4
from packages.media.video_downloader import async_download_video_and_description

AUDIO_FOLDER = "audio/"

logger = logging.getLogger(__name__)


def _with_pipeline_suffix(path: str, pipeline_id: int) -> str:
    p = Path(path)
    if not p.suffix:
        return f"{path}_{pipeline_id}"
    return str(p.with_name(f"{p.stem}_{pipeline_id}{p.suffix}"))


async def process_video_pipeline(url: str, message: Message, context: PTBContext, pipeline_id: int) -> None:
    """Основной конвейер обработки видео:
    1) Скачиваем видео и описание
    2) Конвертируем в mp4
    3) Загружаем в канал и получаем file_id
    4) Извлекаем аудио
    5) Распознаём текст
    6) Генерируем рецепт через AI
    7) Отправляем пользователю на подтверждение
    8) (в save_recipe_handler) сохраняем в БД, если подтвердил
    В случае ошибок — уведомляем пользователя.
    9) Чистим временные файлы
    """
    chat_id = message.chat_id if hasattr(message, "chat_id") else message.chat.id

    notifier = TelegramNotifier(context.bot, chat_id, context=context, source_message=message)
    notifier.message_id = None
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

    upload_task: asyncio.Task[str | None] = asyncio.create_task(send_video_to_channel(context, converted_path))

    if context.user_data is not None:
        pipelines = context.user_data.setdefault("pipelines", {})
        entry = pipelines.setdefault(pipeline_id, {})
        entry["video_path"] = converted_path
        entry["video_upload_task"] = upload_task
    await notifier.progress(60, "✅ Видео загружено. Распознаём текст...")

    audio_path = extract_audio(converted_path, AUDIO_FOLDER)
    transcribe_task = asyncio.create_task(async_transcribe_audio(audio_path))

    def _cleanup_audio_after_done(_task: asyncio.Task) -> None:
        safe_remove(audio_path)

    transcribe_task.add_done_callback(_cleanup_audio_after_done)
    transcript = await transcribe_task

    await notifier.progress(80, "🧠 Подготавливаем рецепт через AI... " "Рецепт практически готов!")

    title, recipe, ingredients = await extract_recipes(description, transcript)

    video_file_id: str | None = None
    try:
        # если аплоад уже успел — получим результат мгновенно
        # таймаут можно убрать, если не нужен контроль зависания
        video_file_id = await upload_task
    except Exception:
        # не валим весь процесс: просто не будет превью из канала
        # (при желании можно notifier.info(...) или notifier.error(...))
        video_file_id = None

    if context.user_data is not None and video_file_id:
        pipelines = context.user_data.setdefault("pipelines", {})
        entry = pipelines.setdefault(pipeline_id, {})
        entry["video_file_id"] = video_file_id
        safe_remove(converted_path)

    if title and recipe and video_file_id:
        await notifier.progress(100, "Готово ✅")
        await send_recipe_confirmation(
            message,
            context,
            title,
            recipe,
            ingredients,
            video_file_id,
            pipeline_id,
            original_url=url,
        )
    else:
        await notifier.error("Не удалось извлечь данные из видео.")
