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
    width, height, sar = _get_video_resolution(input_path)

    logger.info(f"Начинаем конвертацию видео: {input_path}")
    if not width or not height:
        logger.error("Не удалось получить разрешение видео для %s", input_path)
        return ""

    # Корректируем разрешение, если необходимо
    display_width = int(round(width * sar))
    corrected_width, corrected_height = _correct_resolution(display_width, height)

    # Логирование размеров для проверки
    logger.info(f"Исходное разрешение видео: {width}x{height}")
    logger.info(f"SAR видео: {sar}")
    logger.info(f"Исправленное разрешение видео: {corrected_width}x{corrected_height}")

    # Уменьшаем разрешение на 40%
    new_width = int(corrected_width * CORRECTION_FACTOR)
    new_height = int(corrected_height * CORRECTION_FACTOR)

    # Корректируем новый размер на 2 (чтобы избежать ошибок при обработке)
    new_width, new_height = _correct_resolution(new_width, new_height)

    logger.info(f"Новое разрешение видео после сжатия: {new_width}x{new_height}")

    try:
        # Выполняем конвертацию с исправленным разрешением
        ffmpeg.input(input_path).output(
            output_path,
            vf=f"scale={new_width}:{new_height},setsar=1",
            vcodec="libx264",
            acodec="aac",
            crf=32,
        ).run()
        logger.info(f"Конвертация завершена: {output_path}")
    except ffmpeg.Error as e:
        logger.error(f"Ошибка при конвертации видео: {e}", exc_info=True)
        return ""

    return output_path


async def async_convert_to_mp4(input_path: str) -> str:
    """Асинхронная версия функции конвертации видео."""
    return await asyncio.to_thread(convert_to_mp4, input_path)


def _get_video_resolution(video_path: str) -> tuple[int | None, int | None, float]:
    """Получаем разрешение видео и SAR."""
    logger.info(f"Получаем разрешение видео: {video_path}")
    if not os.path.exists(video_path):
        logger.error(f"Видео {video_path} не найдено перед конвертацией")
        return None, None, 1.0
    try:
        probe = ffmpeg.probe(
            video_path,
            v="error",
            select_streams="v:0",
            show_entries="stream=width,height,sample_aspect_ratio,display_aspect_ratio",
        )
        width = probe["streams"][0]["width"]
        height = probe["streams"][0]["height"]
        sar_raw = probe["streams"][0].get("sample_aspect_ratio") or ""
        dar_raw = probe["streams"][0].get("display_aspect_ratio") or ""
        sar = _parse_ratio(sar_raw)
        dar = _parse_ratio(dar_raw)
        if sar is None:
            if dar is None:
                dar = 9 / 16
            sar = (height * dar / width) if width else 1.0
        logger.info(f"Разрешение видео: {width}x{height} sar={sar_raw or 'n/a'} dar={dar_raw or 'n/a'}")
        return width, height, sar
    except ffmpeg.Error as e:
        logger.error(f"Ошибка при анализе видео: {e}", exc_info=True)
        return None, None, 1.0


def _correct_resolution(width: int, height: int) -> tuple[int, int]:
    """Корректируем разрешение видео, чтобы оно делилось на 2"""
    width = max(2, width - (width % 2))
    height = max(2, height - (height % 2))
    return width, height


def _parse_ratio(value: str) -> float | None:
    """Преобразует строку вида 'num:den' в float."""
    try:
        if not value:
            return None
        if ":" not in value:
            return float(value)
        num_str, den_str = value.split(":", 1)
        num = float(num_str)
        den = float(den_str)
        if den == 0:
            return None
        return num / den
    except (ValueError, TypeError):
        return None
