import asyncio
import logging

import whisper

# Загружаем модель Whisper (можно выбрать другую, например, 'medium', 'large')
model = whisper.load_model("base")

logger = logging.getLogger(__name__)


def transcribe_audio(audio_path: str) -> str:
    """Распознаёт речь из аудиофайла."""
    logger.debug(f"Начинаем транскрибацию аудио: {audio_path}")

    try:
        result = model.transcribe(audio_path)
        # Логируем первые 100 символов текста
        logger.debug(f'Распознанный текст: {result["text"][:100]}...')
        return str(result["text"])
    except Exception as e:
        logger.error(f"Ошибка при транскрибации: {e}")
        return ""


async def async_transcribe_audio(audio_path: str) -> str:
    return await asyncio.to_thread(transcribe_audio, audio_path)
