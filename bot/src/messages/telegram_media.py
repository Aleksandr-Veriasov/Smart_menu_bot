import asyncio
import logging
import random
from pathlib import Path
from typing import Final

import ffmpeg
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import FSInputFile

from packages.common_settings.settings import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES: Final[int] = 4
_BASE_DELAY_SEC: Final[float] = 1.5
_MAX_JITTER_SEC: Final[float] = 0.4


def _probe_video_dimensions(video_path: Path) -> tuple[int | None, int | None]:
    """Возвращает размеры видео (width, height) или (None, None) при ошибке."""
    try:
        probe = ffmpeg.probe(
            str(video_path),
            v="error",
            select_streams="v:0",
            show_entries="stream=width,height",
        )
        stream = probe.get("streams", [{}])[0]
        return stream.get("width"), stream.get("height")
    except ffmpeg.Error as exc:
        logger.warning("Не удалось определить размеры видео %s: %s", video_path, exc)
        return None, None


async def send_video_to_channel(
    bot: Bot,
    converted_video_path: str,
    *,
    caption: str = "📹 Новое видео!",
    max_retries: int = _MAX_RETRIES,
) -> str:
    """
    Функция отправляет видео в канал и возвращает ссылку на видео.
    """
    p = Path(converted_video_path)
    if not p.is_file():
        logger.error("Видео не найдено: %s", p)
        return ""

    width, height = _probe_video_dimensions(p)

    for attempt in range(1, max_retries + 1):
        try:
            msg = await bot.send_video(
                chat_id=settings.telegram.chat_id,
                video=FSInputFile(str(p), filename=p.name),
                caption=caption,
                supports_streaming=True,
                width=width,
                height=height,
            )

            file_id = msg.video.file_id if msg.video else ""
            logger.debug(
                "✅ Видео отправлено (attempt=%s): file_id=%s, message_id=%s",
                attempt,
                file_id,
                msg.message_id,
            )
            return file_id

        except TelegramRetryAfter as e:
            # Telegram попросил подождать (Flood/429)
            wait_for = max(float(getattr(e, "retry_after", 1)), 1.0)
            logger.warning(
                "⏳ RetryAfter: ждём %.1fs (attempt %s/%s)",
                wait_for,
                attempt,
                max_retries,
            )
            await asyncio.sleep(wait_for)

        except TelegramNetworkError as e:
            # Временные сетевые сбои/таймауты (обрыв соединения и т.п.)
            if attempt >= max_retries:
                logger.error(
                    "❌ NetworkError: %s. Попытки исчерпаны (%s/%s)",
                    e,
                    attempt,
                    max_retries,
                )
                break
            backoff = _BASE_DELAY_SEC * (2 ** (attempt - 1)) + random.uniform(0, _MAX_JITTER_SEC)
            logger.warning(
                "🌐 NetworkError: %s. Повтор через %.2fs (attempt %s/%s)",
                e,
                backoff,
                attempt,
                max_retries,
            )
            await asyncio.sleep(backoff)

        except TelegramBadRequest as e:
            # Невалидные данные (например, файл слишком большой / неверные
            # параметры) — ретраить бессмысленно
            logger.error("❌ BadRequest при отправке видео: %s", e, exc_info=True)
            return ""

        except Exception as e:
            # Любая другая ошибка — логируем и выходим
            # (обычно нет смысла ретраить неизвестные исключения)
            logger.error("💥 Неожиданная ошибка при отправке видео: %s", e, exc_info=True)
            return ""

    # если все попытки ушли в ретраи, но успеха нет
    return ""
