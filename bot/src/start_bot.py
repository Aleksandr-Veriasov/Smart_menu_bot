"""Точка входа бота: настройка логирования и выбор транспорта (polling/webhook)."""

import asyncio
import logging

from bot.src.application.polling import run_polling
from bot.src.application.webhook import serve_webhook
from packages.common_settings.settings import settings
from packages.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def main() -> None:
    if settings.telegram.use_webhook:
        # Режим вебхука: поднимаем FastAPI-сервер внутри этого процесса.
        serve_webhook()
        return

    # Классический режим: polling.
    try:
        asyncio.run(run_polling())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    except Exception:
        logger.exception("🔥 Ошибка при запуске бота (polling)")
        raise


if __name__ == "__main__":
    main()
