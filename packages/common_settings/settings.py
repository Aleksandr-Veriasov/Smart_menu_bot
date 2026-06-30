from __future__ import annotations

import json
import logging
import os
import ssl
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AnyUrl,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.engine import URL

from packages.common_settings.base import BaseAppSettings

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = Path(os.getenv("PROJECT_ROOT", DEFAULT_BASE_DIR))
APP_DIR = BASE_DIR / "app"


class SslMode(str, Enum):
    """
    Режимы SSL для подключения к PostgreSQL.
    Используется в SQLAlchemy URL.
    """

    disable = "disable"  # нет SSL
    require = "require"  # SSL без строгой валидации (аналог prefer/require)
    verify_ca = "verify-ca"  # проверка цепочки CA
    verify_full = "verify-full"  # проверка CA + имени хоста


class DbDumpDropboxSettings(BaseAppSettings):
    """Конфигурация Dropbox для загрузки и ротации дампов БД."""

    refresh_token: SecretStr = Field(default=SecretStr(""), alias="DB_DUMP_DROPBOX_REFRESH_TOKEN")
    app_key: SecretStr = Field(default=SecretStr(""), alias="DB_DUMP_DROPBOX_APP_KEY")
    app_secret: SecretStr = Field(default=SecretStr(""), alias="DB_DUMP_DROPBOX_APP_SECRET")
    root_path: str = Field(default="/smartmenu/db", alias="DB_DUMP_DROPBOX_ROOT_PATH")

    timeout_sec: int = 120
    api_base: str = "https://api.dropboxapi.com/2/files"
    content_api_base: str = "https://content.dropboxapi.com/2/files"
    oauth_api_base: str = "https://api.dropboxapi.com/oauth2"
    chunk_size_bytes: int = 8 * 1024 * 1024

    @model_validator(mode="after")
    def _validate_auth(self) -> DbDumpDropboxSettings:
        has_refresh_flow = all(
            [
                self.refresh_token.get_secret_value().strip(),
                self.app_key.get_secret_value().strip(),
                self.app_secret.get_secret_value().strip(),
            ]
        )
        if not has_refresh_flow:
            raise ValueError("DB dump Dropbox config incomplete: set refresh_token + app_key + app_secret")
        return self

    def safe_dict(self) -> dict[str, Any]:
        return {
            "refresh_token": "***",
            "app_key": "***",
            "app_secret": "***",
            "root_path": self.root_path,
            "timeout_sec": self.timeout_sec,
            "api_base": self.api_base,
            "content_api_base": self.content_api_base,
            "oauth_api_base": self.oauth_api_base,
            "chunk_size_bytes": self.chunk_size_bytes,
        }


class DatabaseSettings(BaseAppSettings):
    """
    Конфигурация БД: собираем DSN из составных полей.
    """

    host: str = Field(..., alias="DB_HOST")
    port: int = Field(default=5432, alias="DB_PORT")
    username: str = Field(..., alias="DB_USER")
    password: SecretStr = Field(..., alias="DB_PASSWORD")
    database_name: str = Field(..., alias="DB_NAME")

    ssl_mode: SslMode | None = Field(default=None, alias="DB_SSLMODE")
    ssl_root_cert_file: str | None = Field(default=None, alias="DB_SSLROOTCERT")  # путь к CA

    # Рантайм-флаги
    # ping перед выдачей коннекта из пула
    pool_pre_ping: bool = Field(default=True, alias="DB_POOL_PRE_PING")
    # время жизни коннекта в пуле
    pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")
    dump_dir: str = Field(default="/app/data/db_dumps", alias="DB_DUMP_DIR")
    dump_schedule_hour_utc: int = Field(default=3, ge=0, le=23, alias="DB_DUMP_SCHEDULE_HOUR_UTC")
    dump_schedule_minute_utc: int = Field(default=0, ge=0, le=59, alias="DB_DUMP_SCHEDULE_MINUTE_UTC")
    dump_dropbox: DbDumpDropboxSettings = Field(default_factory=DbDumpDropboxSettings)
    # Внутренние дефолты дампов (без ENV)
    dump_filename_prefix: str = "smartmenu"
    dump_pg_timeout_sec: int = 300
    dump_retention_days: int = 14

    @model_validator(mode="after")
    def _validate_required(self) -> DatabaseSettings:
        problems = []
        if not self.host.strip():
            problems.append("host")
        if not self.username.strip():
            problems.append("username")
        if not self.password.get_secret_value().strip():
            problems.append("password")
        if not self.database_name.strip():
            problems.append("database_name")
        if problems:
            raise ValueError(f'DB config incomplete: set {", ".join(problems)}')
        return self

    @property
    def _is_local_host(self) -> bool:
        h = self.host.lower()
        return h in {"localhost", "127.0.0.1", "::1", "db"}

    def _effective_ssl_mode(self, *, use_async: bool = True) -> SslMode | None:
        """
        Если ssl_mode явно не задан в .env:
        - для локальных хостов — SSL не используем,
        - для прочих — 'require' как безопасный дефолт.
        """
        if self.ssl_mode is not None:
            return self.ssl_mode
        return SslMode.disable if self._is_local_host else SslMode.require

    def sqlalchemy_url(self, *, use_async: bool = True) -> URL:
        """
        Собирает SQLAlchemy URL.
        - use_async=True  -> postgresql+asyncpg
        - use_async=False -> postgresql+psycopg (для Alembic)
        """
        driver = "asyncpg" if use_async else "psycopg"
        effective_ssl = self._effective_ssl_mode(use_async=use_async)

        # Параметры в query нужны только для sync-драйвера (libpq-style).
        raw_query: dict[str, str] = {}
        if not use_async and effective_ssl:
            raw_query["sslmode"] = effective_ssl.value
            if self.ssl_root_cert_file:
                raw_query["sslrootcert"] = self.ssl_root_cert_file

        query: dict[str, Sequence[str] | str] = {k: v for k, v in raw_query.items()}

        return URL.create(
            drivername=f"postgresql+{driver}",
            username=self.username,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.database_name,
            query=query,
        )

    def connect_args_for_sqlalchemy(self, *, use_async: bool = True) -> dict[str, Any]:
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
            raise ValueError(f"Unsupported ssl_mode: {effective_ssl}")

        return {"ssl": ctx}

    # Удобно логировать безопасно
    def safe_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": "***",
            "database_name": self.database_name,
            "ssl_mode": self._effective_ssl_mode(),
            "ssl_root_cert_file": self.ssl_root_cert_file,
            "dump_dir": self.dump_dir,
            "dump_schedule_hour_utc": self.dump_schedule_hour_utc,
            "dump_schedule_minute_utc": self.dump_schedule_minute_utc,
            "dump_dropbox": self.dump_dropbox.safe_dict(),
            "dump_filename_prefix": self.dump_filename_prefix,
            "dump_pg_timeout_sec": self.dump_pg_timeout_sec,
            "dump_retention_days": self.dump_retention_days,
        }


class RedisSettings(BaseAppSettings):
    """
    Конфигурация Redis. Cобираем DSN из составных полей.
    """

    host: str = Field(alias="REDIS_HOST")
    port: str = Field(alias="REDIS_PORT")
    password: SecretStr = Field(alias="REDIS_PASSWORD")
    db: str = Field(alias="REDIS_DB")

    def dsn(self) -> str:
        return f"redis://:{self.password.get_secret_value()}" f"@{self.host}:{self.port}/{self.db}"

    def prefix(self) -> str:
        explicit = (os.getenv("REDIS_PREFIX") or "").strip()
        if explicit:
            return explicit
        name = (os.getenv("APP_NAME") or "myapp").strip() or "myapp"
        env = (os.getenv("APP_ENV") or "dev").strip() or "dev"
        return f"{name}:{env}"


class TelegramSettings(BaseAppSettings):
    """
    Конфигурация Telegram бота: токен и ID чата. Используется для отправки уведомлений и логов.
    """

    bot_token: SecretStr = Field(alias="TELEGRAM_BOT_TOKEN")
    chat_id: str = Field(alias="TELEGRAM_CHAT_ID")
    admin_id: int = Field(alias="TELEGRAM_ADMIN_ID")
    use_webhook: bool = Field(default=False, alias="TELEGRAM_USE_WEBHOOK")

    recipes_per_page: int = 5


class BroadcastSettings(BaseAppSettings):
    """
    Очередь массовых рассылок (outbox + worker).
    Управляется из кабинета (SQLAdmin): создаём кампанию, ставим status='queued'.
    """

    enabled: bool = Field(default=True, alias="BROADCAST_ENABLED")
    tick_seconds: float = Field(default=600, ge=0.2, alias="BROADCAST_TICK_SECONDS")
    batch_size: int = Field(default=50, ge=1, le=1000, alias="BROADCAST_BATCH_SIZE")
    request_timeout_sec: float = Field(default=12.0, ge=1.0, le=60.0, alias="BROADCAST_REQUEST_TIMEOUT_SEC")
    # Безопасный дефолт ниже лимитов Telegram (30 msg/sec глобально).
    max_messages_per_second: float = Field(default=10.0, ge=1.0, le=30.0, alias="BROADCAST_MAX_MPS")
    max_attempts: int = Field(default=8, ge=1, le=50, alias="BROADCAST_MAX_ATTEMPTS")
    lock_ttl_sec: int = Field(default=650, ge=5, le=900, alias="BROADCAST_LOCK_TTL_SEC")


class DeepSeekSettings(BaseAppSettings):
    """
    Конфигурация DeepSeek API: ключ API. Используется для доступа к DeepSeek сервисам.
    """

    api_key: SecretStr = Field(alias="DEEPSEEK_API_KEY")
    base_url: str = Field(alias="DEEPSEEK_BASE_URL")
    model: str = Field(alias="DEEPSEEK_MODEL")


class SentrySettings(BaseAppSettings):
    """
    Конфигурация Sentry: DSN для отправки ошибок.
    Используется для мониторинга и отслеживания ошибок.
    """

    dsn: AnyUrl | None = Field(default=None, alias="SENTRY_DSN")


class AdminSettings(BaseAppSettings):
    """
    Конфигурация пользователя Admin
    """

    login: str = Field(alias="ADMIN_LOGIN")
    password: SecretStr = Field(alias="ADMIN_PASSWORD")
    create_on_startup: bool = Field(default=True, alias="ADMIN_CREATE_ON_STARTUP")


class SecuritySettings(BaseAppSettings):
    """Конфигурация пароля"""

    password_pepper: SecretStr | None = Field(default=None, alias="PASSWORD_PEPPER")


class WebHookSettings(BaseAppSettings):
    """Конфигурация вебхуков"""

    prefix: str = Field(default="tg", alias="WEBHOOK_PREFIX")
    slug: str = Field(alias="WEBHOOK_SLUG")
    use_https: bool = True
    secret_token: SecretStr = Field(alias="WEBHOOK_SECRET_TOKEN")
    port: int = Field(default=8081, alias="WEBHOOK_PORT")

    def base_url(self) -> str:
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{settings.fast_api.external_domain()}"

    def path(self) -> str:
        return f"/{self.prefix}/{self.slug}"

    def url(self) -> str:
        return self.base_url() + self.path()


class FastApiSettings(BaseAppSettings):
    """Конфигратор FastAPI"""

    # Если задано и DEBUG=true, base_url() вернёт это значение.
    # Удобно для локальной разработки через ngrok/cloudflared.
    debug_base_url: str | None = Field(default=None, alias="FASTAPI_DEBUG_BASE_URL")

    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"],
        alias="ALLOWED_HOSTS",
    )
    use_https: bool = True
    serve_from_app: bool = Field(
        default=False,
        alias="SERVE_STATIC_FROM_APP",
        description=("В dev=True (FastAPI монтирует /static и /media), " "в prod=False (отдаёт Nginx)."),
    )
    uvicorn_workers: int = Field(default=1, alias="UVICORN_WORKERS")
    mount_static_url: str = "/static"
    static_dir: Path = APP_DIR / "static"
    mount_media_url: str = "/media"
    media_dir: Path = APP_DIR / "media"

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def split_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        # поддержка 'a,b,c' и списков
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    def external_domain(self, *, debug: bool | None = None) -> str:
        """
        Если debug=True → всегда localhost.
        Если debug=False → первый публичный домен из allowed_hosts,
        иначе первый элемент или 'localhost'.
        """
        if debug is True:
            return "localhost"
        for h in self.allowed_hosts:
            if h and h not in ("localhost", "127.0.0.1") and "." in h:
                return h
        return self.allowed_hosts[0] if self.allowed_hosts else "localhost"

    def base_url(self) -> str:
        if settings.debug and self.debug_base_url and self.debug_base_url.strip():
            return self.debug_base_url.strip().rstrip("/")
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.external_domain()}"


class Settings(BaseAppSettings):
    """
    Основные настройки приложения: окружение, отладка,
    конфигурация БД, Telegram, DeepSeek и Sentry.
    """

    env: Literal["local", "dev", "staging", "prod"] = Field(default="prod", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    broadcast: BroadcastSettings = Field(default_factory=BroadcastSettings)
    deepseek: DeepSeekSettings = Field(default_factory=DeepSeekSettings)
    sentry: SentrySettings = Field(default_factory=SentrySettings)
    # 🔹 CORS: список доменов, которым можно слать запросы к API
    cors_origins_raw: str | None = Field(default=None, alias="CORS_ORIGINS")
    admin: AdminSettings = Field(default_factory=AdminSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    webhooks: WebHookSettings = Field(default_factory=WebHookSettings)
    fast_api: FastApiSettings = Field(default_factory=FastApiSettings)

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
            return ["http://localhost:5173", "http://127.0.0.1:5173"]
        # пробуем JSON
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
        # иначе — CSV
        return [x.strip() for x in s.split(",") if x.strip()]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "env": self.env,
            "debug": self.debug,
            "db": self.db.safe_dict(),
            "telegram": {"chat_id": self.telegram.chat_id, "bot_token": "***"},
            "broadcast": {
                "enabled": self.broadcast.enabled,
                "tick_seconds": self.broadcast.tick_seconds,
                "batch_size": self.broadcast.batch_size,
                "request_timeout_sec": self.broadcast.request_timeout_sec,
                "max_messages_per_second": self.broadcast.max_messages_per_second,
                "max_attempts": self.broadcast.max_attempts,
                "lock_ttl_sec": self.broadcast.lock_ttl_sec,
            },
            "deepseek": {"api_key": "***"},
            "sentry": {"dsn": "***" if self.sentry.dsn else None},
            "admin": {"password": "***"},
            "security": {"password_pepper": "***"},
            "redis": {"password": "***"},
            "webhooks": {"secret_token": "***", "slug": "****"},
        }


# Инициализация с fail-fast и безопасным логированием
try:
    settings = Settings()
    logger.info("✅ Конфигурация загружена")
    logger.debug("Дамп конфигурации: %s", settings.safe_dict())
except ValidationError as e:
    logger.critical("❌ Ошибка конфигурации: %s", e.errors())
    raise SystemExit("Остановка: отсутствуют обязательные " "переменные окружения или заданы неверно.") from e
