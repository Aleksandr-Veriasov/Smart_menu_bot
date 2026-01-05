import html
import logging
import os
import sys

import requests
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration


class CustomFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(fmt="[%(asctime)s] %(levelname)s - %(filename)s:%(lineno)d" " - %(name)s - %(message)s")


class APINotificationHandler(logging.Handler):
    def __init__(self, token: str, admin: int) -> None:
        super().__init__()
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.admin = admin
        self.formatter = CustomFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Форматируем и экранируем HTML
            log_entry = self.format(record)
            log_entry = log_entry.replace("[", "\n[").replace("]", "]\n").replace("__ -", "__ -\n")
            safe = html.escape(log_entry)
            payload = {
                "chat_id": self.admin,
                "text": f"<code>{safe}</code>",
                "parse_mode": "HTML",
            }
            # обязательно таймаут, чтобы не подвесить логирование
            requests.post(self.url, json=payload, timeout=5)
        except Exception:
            # Не роняем приложение, если отправка в телегу упала
            self.handleError(record)


NOISY_LOGGERS = {
    "httpcore.connection": logging.INFO,
    "httpcore.http11": logging.INFO,
    "httpcore.proxy": logging.INFO,
    "httpx": logging.ERROR,
    "websockets.client": logging.INFO,
    "sqlalchemy.engine.Engine": logging.ERROR,
    "python_multipart.multipart": logging.INFO,
    "urllib3": logging.WARNING,
    "uvicorn": logging.INFO,  # при желании: DEBUG
    "uvicorn.error": logging.INFO,  # при желании: DEBUG
    "uvicorn.access": logging.INFO,  # access-лог обычно шумный
}


def setup_logging() -> None:
    """Настраивает логирование и интеграцию с Sentry."""
    settings = None
    try:
        from packages.common_settings.settings import settings as default_settings

        settings = default_settings
    except Exception:
        settings = None

    debug = _env_bool("DEBUG", default=False)
    if settings is not None:
        debug = bool(getattr(settings, "debug", debug))

    level = logging.DEBUG if debug else logging.INFO

    for h in logging.root.handlers[:]:
        logging.root.removeHandler(h)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(CustomFormatter())

    logging.basicConfig(
        level=level,
        handlers=[stream_handler],
        # format не нужен: форматтер уже на хендлере
    )

    # ВАЖНО: уровень корневого логгера явно
    logging.getLogger().setLevel(level)

    # Хендлер для Telegram — вешаем на root, чтобы ловить ошибки везде
    telegram = getattr(settings, "telegram", None) if settings is not None else None
    telegram_admin = None
    telegram_token = None
    if telegram is not None:
        telegram_admin = getattr(telegram, "admin_id", None)
        telegram_token = getattr(telegram, "bot_token", None)
    if telegram_admin is None:
        telegram_admin = os.getenv("TELEGRAM_ADMIN_ID")
    if telegram_token is None:
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

    if telegram_admin and telegram_token:
        api_handler = APINotificationHandler(
            str(telegram_token),
            int(telegram_admin),
        )
        api_handler.setLevel(logging.ERROR)  # только ERROR и выше в Telegram
        logging.getLogger().addHandler(api_handler)

    # Подкручиваем уровни «шумных» логгеров
    for name, lvl in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl if debug else max(lvl, logging.INFO))

    # Пробный вывод, чтобы убедиться что DEBUG реально виден
    test_logger = logging.getLogger(__name__)
    test_logger.debug("✅ DEBUG активен")
    test_logger.info("ℹ️ INFO активен")

    sentry = getattr(settings, "sentry", None) if settings is not None else None
    sentry_dsn = getattr(sentry, "dsn", None) if sentry is not None else None
    env_name = getattr(settings, "env", None) if settings is not None else None
    if sentry_dsn is None:
        sentry_dsn = os.getenv("SENTRY_DSN")
    if env_name is None:
        env_name = os.getenv("APP_ENV", "prod")

    if sentry_dsn and debug is False:
        sentry_sdk.init(
            dsn=str(sentry_dsn),
            send_default_pii=False,
            _experiments={"enable_logs": True},
            integrations=[LoggingIntegration(sentry_logs_level=logging.WARNING)],
            environment=env_name,
            traces_sample_rate=1.0,
        )
        logging.getLogger(__name__).info("✅ Sentry инициализирован.")
    else:
        logging.getLogger(__name__).warning("⚠️ SENTRY_DSN не задан. Sentry не активен.")


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
