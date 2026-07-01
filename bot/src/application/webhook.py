"""Транспорт webhook: FastAPI-приложение, lifespan и приём апдейтов Telegram."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from prometheus_fastapi_instrumentator import Instrumentator

from bot.src.application.factory import build_bot, build_dispatcher, build_state
from bot.src.application.lifecycle import runtime_start, runtime_stop
from packages.common_settings.settings import settings
from packages.db.pool_metrics import register_pool_metrics

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Поднимает aiogram Bot/Dispatcher и ресурсы на время жизни FastAPI."""
    logger.info("🚀 Запуск webhook-сервера FastAPI…")
    state = build_state()
    bot = build_bot()

    try:
        dp = await build_dispatcher(state)

        register_pool_metrics(state.db.engine, service="bot")
        await runtime_start(bot, state, allowed_updates=dp.resolve_used_update_types())

        # сохраним в app.state, чтобы роуты имели доступ
        app.state.bot = bot
        app.state.dp = dp
        logger.info("✅ aiogram-приложение запущено (режим webhook).")

        yield
    finally:
        logger.info("🛑 Остановка webhook-сервера…")
        await runtime_stop(state)
        with suppress(Exception):
            await bot.session.close()
        await asyncio.sleep(0.25)
        app.state.bot = None
        app.state.dp = None


fastapi_app = FastAPI(title="Webhook Telegram-бота", lifespan=lifespan)
Instrumentator().instrument(fastapi_app).expose(fastapi_app, endpoint="/metrics", include_in_schema=False)


@fastapi_app.post(settings.webhooks.path())
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """
    Обработчик вебхука Telegram.
    Bot/Dispatcher инициализируются в lifespan и хранятся в app.state.
    """
    bot: Bot | None = getattr(request.app.state, "bot", None)
    dp: Dispatcher | None = getattr(request.app.state, "dp", None)
    if bot is None or dp is None:
        raise HTTPException(status_code=503, detail="Бот ещё не готов")

    # Проверка секрета от Telegram (защита от «левых» POST)
    secret_hdr = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_hdr != settings.webhooks.secret_token.get_secret_value():
        raise HTTPException(status_code=403, detail="Некорректный secret token")

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


def serve_webhook() -> None:
    """Поднимает uvicorn-сервер с FastAPI-приложением (режим webhook)."""
    import uvicorn

    uvicorn.run(
        fastapi_app,
        host="0.0.0.0",
        port=settings.webhooks.port,
        workers=settings.fast_api.uvicorn_workers,
        log_level="info",
    )
