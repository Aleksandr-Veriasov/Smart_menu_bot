"""Троттлинг правок сообщений Telegram.

Используется как синхронно (media_worker), так и асинхронно (bot/aiogram).
"""

import asyncio
import time


class EditThrottle:
    """Следит за временем последней правки и делает паузу при необходимости."""

    def __init__(self, min_interval: float = 1.0) -> None:
        self._min_interval = min_interval
        self._last_ts: float = 0.0

    def _gap(self) -> float:
        return max(0.0, self._min_interval - (time.monotonic() - self._last_ts))

    def wait_sync(self) -> None:
        """Синхронная пауза перед правкой."""
        gap = self._gap()
        if gap:
            time.sleep(gap)

    async def wait_async(self) -> None:
        """Асинхронная пауза перед правкой."""
        gap = self._gap()
        if gap:
            await asyncio.sleep(gap)

    def mark(self) -> None:
        """Зафиксировать момент успешной правки."""
        self._last_ts = time.monotonic()
