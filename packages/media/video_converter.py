import asyncio
import logging
import os

import ffmpeg

logger = logging.getLogger(__name__)


CORRECTION_FACTOR = 0.6  # Уменьшение разрешения на 40%


def convert_to_mp4(input_path: str) -> str:
    """Конвертирует видео в MP4 (H.264) с уменьшением качества на 40%."""
    output_path = input_path.rsplit(".", 1)[0] + "_converted.mp4"

    # Получаем исходное разрешение видео
    width, height = _get_video_resolution(input_path)

    logger.debug(f"Начинаем конвертацию видео: {input_path}")
    if not width or not height:
        logger.error("Не удалось получить разрешение видео для %s", input_path)
        return ""

    # Корректируем разрешение, если необходимо
    corrected_width, corrected_height = _correct_resolution(width, height)

    # Логирование размеров для проверки
    logger.debug(f"Исходное разрешение видео: {width}x{height}")
    logger.debug(f"Исправленное разрешение видео: {corrected_width}x{corrected_height}")

    # Уменьшаем разрешение на 40%
    new_width = int(corrected_width * CORRECTION_FACTOR)
    new_height = int(corrected_height * CORRECTION_FACTOR)

    # Корректируем новый размер на 2 (чтобы избежать ошибок при обработке)
    new_width, new_height = _correct_resolution(new_width, new_height)

    logger.debug(f"Новое разрешение видео после сжатия: {new_width}x{new_height}")

    try:
        # Выполняем конвертацию с исправленным разрешением
        ffmpeg.input(input_path).output(
            output_path,
            vf=f"scale={new_width}:{new_height},setsar=1",
            vcodec="libx264",
            acodec="aac",
            crf=32,
        ).run()
        logger.debug(f"Конвертация завершена: {output_path}")
    except ffmpeg.Error as e:
        logger.error(f"Ошибка при конвертации видео: {e}", exc_info=True)
        return ""

    return output_path


async def async_convert_to_mp4(input_path: str) -> str:
    """Асинхронная версия функции конвертации видео."""
    return await asyncio.to_thread(convert_to_mp4, input_path)


def _get_video_resolution(video_path: str) -> tuple[int | None, int | None]:
    """Получаем разрешение видео"""
    logger.debug(f"Получаем разрешение видео: {video_path}")
    if not os.path.exists(video_path):
        logger.error("Видео %s не найдено перед конвертацией", video_path)
        return None, None
    try:
        probe = ffmpeg.probe(
            video_path,
            v="error",
            select_streams="v:0",
            show_entries="stream=width,height",
        )
        width = probe["streams"][0]["width"]
        height = probe["streams"][0]["height"]
        logger.debug(f"Разрешение видео: {width}x{height}")
        return width, height
    except ffmpeg.Error as e:
        logger.error(f"Ошибка при анализе видео: {e}", exc_info=True)
        return None, None


def _correct_resolution(width: int, height: int) -> tuple[int, int]:
    """Корректируем разрешение видео, чтобы оно делилось на 2"""
    width = max(2, width - (width % 2))
    height = max(2, height - (height % 2))
    return width, height
