from __future__ import annotations

import json
import logging
import os
import ssl
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional, Tuple, get_args, get_origin

from pydantic import (
    AnyUrl,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import (
    EnvSettingsSource,
    PydanticBaseSettingsSource,
)
from sqlalchemy.engine import URL

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = Path(os.getenv('PROJECT_ROOT', DEFAULT_BASE_DIR))
APP_DIR = BASE_DIR / 'app'


class FileAwareEnvSource(EnvSettingsSource):
    """
    Источник ENV с поддержкой fallback на <ENV>_FILE.
    Приоритет: ENV > ENV_FILE.
    """

    def get_field_value(
            self, field: FieldInfo, field_name: str
    ) -> Tuple[Any, str, bool]:
        # 1) Берём стандартное значение из окружения
        value, key, is_complex = super().get_field_value(field, field_name)

        # 2) Если пусто — пробуем <KEY>_FILE
        if value in (None, ''):
            file_env = f'{key}_FILE'  # key уже учитывает env_prefix и alias
            file_path = os.getenv(file_env)
            if file_path:
                p = Path(file_path).expanduser().resolve()
                if not p.is_file():
                    raise ValueError(f'{file_env} points to missing file: {p}')
                value = p.read_text().strip()
                # Содержимое файла — обычная строка (не JSON и т.п.)
                is_complex = False

        # 3) Если значение строка и pydantic считает его 'complex',
        #    но строка НЕ похожа на JSON — отдаём как plain string
        if isinstance(value, str):
            s = value.strip()

            # определяем, что поле — list[str]
            origin = get_origin(field.annotation)
            args = get_args(field.annotation)
            is_list_of_str = (
                origin in (list, tuple)
            ) and (len(args) == 1 and args[0] is str)

            # строка 'не похожа' на JSON?
            looks_like_json = (
                s.startswith('[') or s.startswith('{') or s.startswith('"') or
                s in ('null', 'true', 'false') or
                (s and s[0] in '-0123456789')
            )

            if is_list_of_str and not looks_like_json:
                # Превратим 'a,b,c' → ['a','b','c'] и оставим is_complex=True
                parts = [x.strip() for x in s.split(',') if x.strip()]
                value = json.dumps(parts)
                is_complex = True  # пусть pydantic сам json.loads(...) сделает

        return value, key, is_complex


class BaseAppSettings(BaseSettings):
    """ Базовый класс настроек приложения с кастомным источником ENV.
    Используется для переопределения источников конфигурации и
    настройки их порядка.
    """
    model_config = SettingsConfigDict(
        env_file='.env',
        case_sensitive=False,
        extra='ignore',
        frozen=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[
        PydanticBaseSettingsSource,
        PydanticBaseSettingsSource,
        PydanticBaseSettingsSource,
        PydanticBaseSettingsSource,
    ]:
        # порядок источников:
        # kwargs -> наш ENV/ENV_FILE -> .env -> secrets_dir
        return (
            init_settings,
            FileAwareEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings
        )


class SslMode(str, Enum):
    """
    Режимы SSL для подключения к PostgreSQL.
    Используется в SQLAlchemy URL.
    """
    disable = 'disable'  # нет SSL
    require = 'require'  # SSL без строгой валидации (аналог prefer/require)
    verify_ca = 'verify-ca'     # проверка цепочки CA
    verify_full = 'verify-full'   # проверка CA + имени хоста


class DatabaseSettings(BaseAppSettings):
    """
    Конфигурация БД: собираем DSN из составных полей.
    """

    host: str = Field(..., alias='DB_HOST')
    port: int = Field(default=5432, alias='DB_PORT')
    username: str = Field(..., alias='DB_USER')
    password: SecretStr = Field(..., alias='DB_PASSWORD')
    database_name: str = Field(..., alias='DB_NAME')

    ssl_mode: Optional[SslMode] = Field(default=None, alias='DB_SSLMODE')
    ssl_root_cert_file: Optional[str] = Field(
        default=None, alias='DB_SSLROOTCERT'
    )  # путь к CA

    # Рантайм-флаги
    # dev-bootstrap: Base.metadata.create_all()
    bootstrap_schema: bool = Field(default=False, alias='DB_BOOTSTRAP_SCHEMA')
    # ping перед выдачей коннекта из пула
    pool_pre_ping: bool = Field(default=True, alias='DB_POOL_PRE_PING')
    # время жизни коннекта в пуле
    pool_recycle: int = Field(default=1800, alias='DB_POOL_RECYCLE')
    run_migrations_on_startup: bool = Field(
        default=True, alias='RUN_MIGRATIONS_ON_STARTUP'
    )

    @model_validator(mode='after')
    def _validate_required(self) -> DatabaseSettings:
        problems = []
        if not self.host.strip():
            problems.append('host')
        if not self.username.strip():
            problems.append('username')
        if not self.password.get_secret_value().strip():
            problems.append('password')
        if not self.database_name.strip():
            problems.append('database_name')
        if problems:
            raise ValueError(
                f'DB config incomplete: set {", ".join(problems)}'
            )
        return self

    @property
    def _is_local_host(self) -> bool:
        h = self.host.lower()
        return h in {'localhost', '127.0.0.1', '::1', 'db'}

    def _effective_ssl_mode(
            self,  *, use_async: bool = True
    ) -> Optional[SslMode]:
        """
        Если ssl_mode явно не задан в .env:
        - для локальных хостов — SSL не используем,
        - для прочих — 'require' как безопасный дефолт.
        """
        if self.ssl_mode is not None and use_async:
            return self.ssl_mode
        return SslMode.disable if self._is_local_host else SslMode.require

    def sqlalchemy_url(self, *, use_async: bool = True) -> URL:
        """
        Собирает SQLAlchemy URL.
        - use_async=True  -> postgresql+asyncpg
        - use_async=False -> postgresql+psycopg (для Alembic)
        """
        driver = 'asyncpg' if use_async else 'psycopg'
        effective_ssl = self._effective_ssl_mode(use_async=use_async)

        # Параметры в query нужны только для sync-драйвера (libpq-style).
        raw_query: dict[str, str] = {}
        if not use_async and effective_ssl:
            raw_query['sslmode'] = effective_ssl.value
            if self.ssl_root_cert_file:
                raw_query['sslrootcert'] = self.ssl_root_cert_file

        query: dict[str, Sequence[str] | str] = {
            k: v for k, v in raw_query.items()
        }

        return URL.create(
            drivername=f'postgresql+{driver}',
            username=self.username,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database_name,
            query=query,
        )

    def connect_args_for_sqlalchemy(
            self, *, use_async: bool = True
    ) -> dict[str, Any]:
        """
        Для asyncpg возвращаем SSL-настройки через ssl.SSLContext.
        Для psycopg (sync) ничего не нужно — всё в URL query.
        """
        if not use_async:
            return {}

        effective_ssl = self._effective_ssl_mode(use_async=use_async)
        if not effective_ssl or effective_ssl == SslMode.disable:
            return {}

        ctx = ssl.create_default_context()

        if effective_ssl == SslMode.require:
            # мягкий SSL — без проверки CA/host
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif effective_ssl in (SslMode.verify_ca, SslMode.verify_full):
            # строгие режимы: проверка CA (+ hostname для verify_full)
            if self.ssl_root_cert_file:
                ctx.load_verify_locations(cafile=self.ssl_root_cert_file)
            if effective_ssl == SslMode.verify_ca:
                # проверяем цепочку, но не hostname
                ctx.check_hostname = False
                # verify_mode остаётся по умолчанию (CERT_REQUIRED)
        else:
            raise ValueError(f'Unsupported ssl_mode: {effective_ssl}')

        return {'ssl': ctx}

    # Удобно логировать безопасно
    def safe_dict(self) -> dict[str, Any]:
        return {
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'password': '***',
            'database_name': self.database_name,
            'ssl_mode': self._effective_ssl_mode(),
            'ssl_root_cert_file': self.ssl_root_cert_file,
        }


class RedisSettings(BaseAppSettings):
    """
    Конфигурация Redis. Cобираем DSN из составных полей.
    """
    host: str = Field(alias='REDIS_HOST')
    port: str = Field(alias='REDIS_PORT')
    password: SecretStr = Field(alias='REDIS_PASSWORD')
    db: str = Field(alias='REDIS_DB')
    prefix: Optional[str] = Field(default=None, alias='REDIS_PREFIX')
    app_env: str = Field(default='dev', alias='APP_ENV')
    app_name: str = Field(default='myapp', alias='APP_NAME')

    def dsn(self) -> str:
        return (
            f'redis://:{self.password.get_secret_value()}'
            f'@{self.host}:{self.port}/{self.db}'
        )

    @classmethod
    def build_prefix(
        cls, *, prefix: Optional[str], app_name: str, app_env: str
    ) -> str:
        """
        Правило:
        - если prefix задан → нормализуем и используем его;
        - иначе собираем из APP_NAME и APP_ENV: "<name>:<env>"
        """
        p = (prefix or "").strip()
        if p:
            return p.strip(":")
        name = (app_name or "myapp").strip()
        env = (app_env or "dev").strip().lower()
        return f"{name}:{env}"

    @property
    def resolved_prefix(self) -> str:
        """
        Финальный префикс с учётом REDIS_PREFIX/APP_NAME/APP_ENV
        (без хвостовых двоеточий).
        """
        return self.build_prefix(
            prefix=self.prefix, app_name=self.app_name, app_env=self.app_env
        )

    def namespaced(self, key: str) -> str:
        """
        Префиксует любой ключ Redis:
        - избегает двойных двоеточий,
        - пустой префикс возвращает исходный key.
        """
        p = self.resolved_prefix.strip(":")
        return f"{p}:{key}" if p else key


class TelegramSettings(BaseAppSettings):
    """
    Конфигурация Telegram бота: токен и ID чата.
    Используется для отправки уведомлений и логов.
    """
    bot_token: SecretStr = Field(alias='TELEGRAM_BOT_TOKEN')
    chat_id: str = Field(alias='TELEGRAM_CHAT_ID')
    admin_id: int = Field(alias='TELEGRAM_ADMIN_ID')
    use_webhook: bool = Field(
        default=False, alias='TELEGRAM_USE_WEBHOOK'
    )

    recipes_per_page: int = 5


class DeepSeekSettings(BaseAppSettings):
    """
    Конфигурация DeepSeek API: ключ API.
    Используется для доступа к DeepSeek сервисам.
    """

    api_key: SecretStr = Field(alias='DEEPSEEK_API_KEY')
    base_url: str = Field(alias='DEEPSEEK_BASE_URL')
    model: str = Field(alias='DEEPSEEK_MODEL')


class SentrySettings(BaseAppSettings):
    """
    Конфигурация Sentry: DSN для отправки ошибок.
    Используется для мониторинга и отслеживания ошибок.
    """

    dsn: Optional[AnyUrl] = Field(default=None, alias='SENTRY_DSN')


class AdminSettinds(BaseAppSettings):
    """
    Конфигурация пользователя Admin
    """
    login: str = Field(alias='ADMIN_LOGIN')
    password: SecretStr = Field(alias='ADMIN_PASSWORD')
    create_on_startup: bool = Field(
        default=True, alias='ADMIN_CREATE_ON_STARTUP'
    )


class SecuritySettings(BaseAppSettings):
    """ Конфигурация пароля """
    password_pepper: SecretStr | None = Field(
        default=None, alias='PASSWORD_PEPPER'
    )


class WebHookSettings(BaseAppSettings):
    """ Конфигурация вебхуков """
    prefix: str = Field(default='tg', alias='WEBHOOK_PREFIX')
    slug: str = Field(alias='WEBHOOK_SLUG')
    use_https: bool = True
    secret_token: SecretStr = Field(alias='WEBHOOK_SECRET_TOKEN')
    port: int = Field(default=8081, alias='WEBHOOK_PORT')

    def base_url(self) -> str:
        scheme = 'https' if self.use_https else 'http'
        return f'{scheme}://{settings.fast_api.external_domain()}'

    def path(self) -> str:
        return f'/{self.prefix}/{self.slug}'

    def url(self) -> str:
        return self.base_url() + self.path()


class FastApiSettings(BaseAppSettings):
    """ Конфигратор FastAPI """
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ['localhost', '127.0.0.1'],
        alias='ALLOWED_HOSTS'
    )
    use_https: bool = True
    serve_from_app: bool = Field(
        default=False,
        alias='SERVE_STATIC_FROM_APP',
        description=(
            'В dev=True (FastAPI монтирует /static и /media), '
            'в prod=False (отдаёт Nginx).'
        )
    )
    uvicorn_workers: int = Field(default=1, alias='UVICORN_WORKERS')
    mount_static_url: str = '/static'
    static_dir: Path = APP_DIR / 'static'
    mount_media_url: str = '/media'
    media_dir: Path = APP_DIR / 'media'

    @field_validator('allowed_hosts', mode='before')
    @classmethod
    def split_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        # поддержка 'a,b,c' и списков
        if isinstance(v, str):
            return [x.strip() for x in v.split(',') if x.strip()]
        return v

    def external_domain(self, *, debug: Optional[bool] = None) -> str:
        """
        Если debug=True → всегда localhost.
        Если debug=False → первый публичный домен из allowed_hosts,
        иначе первый элемент или 'localhost'.
        """
        if debug is True:
            return 'localhost'
        for h in self.allowed_hosts:
            if h and h not in ('localhost', '127.0.0.1') and '.' in h:
                return h
        return self.allowed_hosts[0] if self.allowed_hosts else 'localhost'

    def base_url(self) -> str:
        scheme = 'https' if self.use_https else 'http'
        return f'{scheme}://{self.external_domain()}'


class StreamsSettings(BaseAppSettings):
    """ Конфигурация потоков задач """
    tasks: str = 'dl:tasks'
    done: str = 'dl:done'
    failed: str = 'dl:failed'
    group_workers: str = 'dl:workers'
    group_bot: str = 'bot'
    maxlen: int = 5000


class DownloadSettings(BaseAppSettings):
    """ Конфигурация загрузки видео """
    videos_dir: str = Field(default='/videos', alias='VIDEOS_DIR')
    max_concurrency: int = 3  # макс. число одновременных загрузок
    ytdlp_retries: int = 3  # число попыток при ошибках ytdlp
    ytdlp_timeout_sec: int = 120  # таймаут одной попытки ytdlp
    playwright_timeout_sec: int = 30  # таймаут Playwright
    ffmpeg_timeout_sec: int = 90  # таймаут ffmpeg
    cleanup_ttl_min: int = 20  # время жизни файлов на диске
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None


class Settings(BaseAppSettings):
    """
    Основные настройки приложения: окружение, отладка,
    конфигурация БД, Telegram, DeepSeek и Sentry.
    """
    env: Literal['local', 'dev', 'staging', 'prod'] = Field(
        default='prod', alias='APP_ENV'
    )
    debug: bool = Field(default=False, alias='DEBUG')

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    deepseek: DeepSeekSettings = Field(default_factory=DeepSeekSettings)
    sentry: SentrySettings = Field(default_factory=SentrySettings)
    # CORS: список доменов, которым можно слать запросы к API
    cors_origins_raw: str | None = Field(default=None, alias='CORS_ORIGINS')
    admin: AdminSettinds = Field(default_factory=AdminSettinds)
    security: SecuritySettings = SecuritySettings()
    redis: RedisSettings = Field(default_factory=RedisSettings)
    webhooks: WebHookSettings = Field(default_factory=WebHookSettings)
    fast_api: FastApiSettings = Field(default_factory=FastApiSettings)
    streams: StreamsSettings = Field(default_factory=StreamsSettings)
    download: DownloadSettings = Field(default_factory=DownloadSettings)

    @property
    def cors_origins(self) -> list[str]:
        """
        Возвращает список доменов для CORS.
        Поддерживает:
         - JSON-список в .env: '['https://a','https://b']'
         - CSV-строку: 'https://a,https://b'
        """
        s = self.cors_origins_raw
        if not s:
            return ['http://localhost:5173', 'http://127.0.0.1:5173']
        # пробуем JSON
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
        # иначе — CSV
        return [x.strip() for x in s.split(',') if x.strip()]

    def safe_dict(self) -> dict[str, Any]:
        return {
            'env': self.env,
            'debug': self.debug,
            'db': self.db.safe_dict(),
            'telegram': {'chat_id': self.telegram.chat_id, 'bot_token': '***'},
            'deepseek': {'api_key': '***'},
            'sentry': {'dsn': '***' if self.sentry.dsn else None},
            'admin': {'password': '***'},
            'security': {'password_pepper': '***'},
            'redis': {'password': '***'},
            'webhooks': {'secret_token': '***', 'slug': '****'},

        }


try:
    settings = Settings()
    logger.info('✅ Конфигурация загружена')
    logger.debug('Config dump: %s', settings.safe_dict())
except ValidationError as e:
    logger.critical('❌ Ошибка конфигурации: %s', e.errors())
    raise SystemExit(
        'Остановка: отсутствуют обязательные '
        'переменные окружения или заданы неверно.'
    )
