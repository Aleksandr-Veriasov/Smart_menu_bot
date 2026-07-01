"""Транспорт polling: long-polling-запуск бота."""

import asyncio
import logging
from contextlib import suppress

from bot.src.application.factory import build_bot, build_dispatcher, build_state
from bot.src.application.lifecycle import runtime_start, runtime_stop

logger = logging.getLogger(__name__)


async def run_polling() -> None:
    """Классический режим: long-polling."""
    state = build_state()
    bot = build_bot()
    dp = await build_dispatcher(state)
    allowed_updates = dp.resolve_used_update_types()

    await bot.delete_webhook(drop_pending_updates=True)
    await runtime_start(bot, state, allowed_updates=allowed_updates)
    logger.info("🤖 Бот запускается (polling)…")
    try:
        await dp.start_polling(bot, allowed_updates=allowed_updates)
    finally:
        await runtime_stop(state)
        with suppress(Exception):
            await bot.session.close()
        await asyncio.sleep(0.25)
