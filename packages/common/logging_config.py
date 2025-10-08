import html
import logging
import sys

import requests
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from packages.common_settings.settings import settings


class CustomFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            fmt='%(filename)s:%(lineno)d #%(levelname)-8s '
            '[%(asctime)s] - %(name)s - %(message)s'
        )


class APINotificationHandler(logging.Handler):
    def __init__(self, token: str, admin: int) -> None:
        super().__init__()
        self.url = f'https://api.telegram.org/bot{token}/sendMessage'
        self.admin = admin
        self.formatter = CustomFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Форматируем и экранируем HTML
            log_entry = self.format(record)
            log_entry = log_entry.replace(
                '[', '\n['
            ).replace(']', ']\n').replace('__ -', '__ -\n')
            safe = html.escape(log_entry)
            payload = {
                'chat_id': self.admin,
                'text': f'<code>{safe}</code>',
                'parse_mode': 'HTML',
            }
            # обязательно таймаут, чтобы не подвесить логирование
            requests.post(self.url, json=payload, timeout=5)
        except Exception:
            # Не роняем приложение, если отправка в телегу упала
            self.handleError(record)


NOISY_LOGGERS = {
    'httpcore.connection': logging.INFO,
    'httpcore.http11': logging.INFO,
    'httpcore.proxy': logging.INFO,
    'httpx': logging.ERROR,
    'websockets.client': logging.INFO,
    'sqlalchemy.engine.Engine': logging.ERROR,
    'python_multipart.multipart': logging.INFO,
    'urllib3': logging.WARNING,
    'uvicorn': logging.INFO,          # при желании: DEBUG
    'uvicorn.error': logging.INFO,    # при желании: DEBUG
    'uvicorn.access': logging.INFO,   # access-лог обычно шумный
}


def setup_logging() -> None:
    """ Настраивает логирование и интеграцию с Sentry. """
    level = logging.DEBUG if settings.debug else logging.INFO

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
    if settings.telegram.admin_id and settings.telegram.bot_token:
        api_handler = APINotificationHandler(
            str(settings.telegram.bot_token),
            int(settings.telegram.admin_id),
        )
        api_handler.setLevel(logging.ERROR)  # только ERROR и выше в Telegram
        logging.getLogger().addHandler(api_handler)

    # Подкручиваем уровни «шумных» логгеров
    for name, lvl in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(
            lvl if settings.debug else max(lvl, logging.INFO)
        )

    # Пробный вывод, чтобы убедиться что DEBUG реально виден
    test_logger = logging.getLogger(__name__)
    test_logger.debug("✅ DEBUG активен")
    test_logger.info("ℹ️ INFO активен")

    if settings.sentry.dsn and settings.debug is False:
        sentry_sdk.init(
            dsn=str(settings.sentry.dsn),
            send_default_pii=False,
            _experiments={'enable_logs': True},
            integrations=[
                LoggingIntegration(sentry_logs_level=logging.WARNING)
            ],
            environment=settings.env,
            traces_sample_rate=1.0,
        )
        logging.getLogger(__name__).info('✅ Sentry инициализирован.')
    else:
        logging.getLogger(__name__).warning(
            '⚠️ SENTRY_DSN не задан. Sentry не активен.'
        )
