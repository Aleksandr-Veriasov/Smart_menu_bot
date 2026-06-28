"""Ленивая загрузка Whisper с TTL-выгрузкой по простою.

Модель грузится при первом вызове transcribe() и выгружается
если не использовалась дольше IDLE_TTL_SECONDS секунд.
Это позволяет media_worker не держать ~1 ГБ в RAM постоянно.
"""

import asyncio
import ctypes
import gc
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_NAME = "base"
_IDLE_TTL_SECONDS = 120  # 2 минуты без запросов → выгрузить

_lock = threading.Lock()
_model: Any = None
_last_used_at: float = 0.0


def _load() -> Any:
    from faster_whisper import (
        WhisperModel,  # импорт только здесь — не при старте воркера
    )

    global _model, _last_used_at
    with _lock:
        if _model is None:
            logger.info("Загружаем faster-whisper модель '%s'…", _MODEL_NAME)
            _model = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
            logger.info("faster-whisper модель загружена")
        _last_used_at = time.monotonic()
        return _model


def _unload() -> None:
    global _model
    with _lock:
        if _model is not None:
            logger.info("Выгружаем Whisper модель (TTL истёк)")
            _model = None
            gc.collect()
            # Вернуть свободные страницы ОС — иначе glibc держит их в пуле
            try:
                ctypes.cdll.LoadLibrary("libc.so.6").malloc_trim(0)
            except Exception:
                pass


def transcribe(audio_path: str) -> str:
    """Синхронная транскрибация. Вызывать через asyncio.to_thread()."""
    model = _load()
    try:
        segments, _ = model.transcribe(audio_path)
        text = " ".join(seg.text for seg in segments).strip()
        logger.debug("Транскрибация завершена: %d символов", len(text))
        return text
    except Exception:
        logger.exception("Ошибка транскрибации '%s'", audio_path)
        return ""
    finally:
        with _lock:
            global _last_used_at
            _last_used_at = time.monotonic()


async def transcribe_async(audio_path: str) -> str:
    return await asyncio.to_thread(transcribe, audio_path)


async def unload_loop() -> None:
    """Фоновая корутина: раз в минуту проверяет TTL и выгружает модель если не нужна."""
    while True:
        await asyncio.sleep(60)
        with _lock:
            idle = time.monotonic() - _last_used_at
            loaded = _model is not None
        if loaded and idle >= _IDLE_TTL_SECONDS:
            _unload()
