from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Final

from telegram import InputFile
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from bot.app.core.types import PTBContext
from packages.common_settings.settings import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES: Final[int] = 4
_BASE_DELAY_SEC: Final[float] = 1.5
_MAX_JITTER_SEC: Final[float] = 0.4


async def send_video_to_channel(
    context: PTBContext,
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

    for attempt in range(1, max_retries + 1):
        try:
            # Каждый раз открываем файл заново — после
            # неудачной попытки поток может быть «исчерпан»
            with p.open("rb") as f:
                msg = await context.bot.send_video(
                    chat_id=settings.telegram.chat_id,
                    video=InputFile(f, filename=p.name),
                    caption=caption,
                    supports_streaming=True,
                    allow_sending_without_reply=True,
                    read_timeout=90,
                    write_timeout=90,
                )

            file_id = msg.video.file_id if msg.video else ""
            logger.debug(
                "✅ Видео отправлено (attempt=%s): file_id=%s, message_id=%s",
                attempt,
                file_id,
                msg.message_id,
            )
            return file_id

        except RetryAfter as e:
            # Telegram попросил подождать (Flood/429)
            wait_for = max(float(getattr(e, "retry_after", 1)), 1.0)
            logger.warning(
                "⏳ RetryAfter: ждём %.1fs (attempt %s/%s)",
                wait_for,
                attempt,
                max_retries,
            )
            await asyncio.sleep(wait_for)

        except TimedOut:
            # Классический таймаут сети/чтения
            if attempt >= max_retries:
                logger.error(
                    "❌ TimedOut. Попытки исчерпаны (%s/%s)",
                    attempt,
                    max_retries,
                )
                break
            backoff = _BASE_DELAY_SEC * (2 ** (attempt - 1)) + random.uniform(0, _MAX_JITTER_SEC)
            logger.warning(
                "⚠️ TimedOut при отправке видео. " "Повтор через %.2fs (attempt %s/%s)",
                backoff,
                attempt,
                max_retries,
            )
            await asyncio.sleep(backoff)

        except NetworkError as e:
            # Временные сетевые сбои (обрыв соединения и т.п.)
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

        except BadRequest as e:
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
