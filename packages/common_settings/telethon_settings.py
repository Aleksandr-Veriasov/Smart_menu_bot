import logging
from functools import lru_cache

from pydantic import Field, SecretStr

from packages.common_settings.base import BaseAppSettings

logger = logging.getLogger(__name__)


class TelethonSettings(BaseAppSettings):
    """Настройки Telethon worker."""

    debug: bool = Field(default=False, alias="DEBUG")
    api_id: int = Field(alias="TG_API_ID")
    api_hash: SecretStr = Field(alias="TG_API_HASH")

    session_path: str = Field(default="/app/sessions/user.session", alias="TELETHON_SESSION_PATH")
    concurrency: int = Field(default=1, alias="TELETHON_CONCURRENCY")

    target_bot: str = Field(default="SaveAsBot", alias="TELETHON_TARGET_BOT")
    download_dir: str = Field(default="/app/videos", alias="TELETHON_DOWNLOAD_DIR")

    timeout_sec: float = Field(default=180, alias="TELETHON_TIMEOUT_SEC")
    edit_timeout_sec: float = Field(default=30, alias="TELETHON_EDIT_TIMEOUT_SEC")

    def safe_dict(self) -> dict[str, str | int | float]:
        return {
            "debug": self.debug,
            "api_id": self.api_id,
            "api_hash": "***",
            "session_path": self.session_path,
            "concurrency": self.concurrency,
            "target_bot": self.target_bot,
            "download_dir": self.download_dir,
            "timeout_sec": self.timeout_sec,
            "edit_timeout_sec": self.edit_timeout_sec,
        }


@lru_cache(maxsize=1)
def get_telethon_settings() -> TelethonSettings:
    """Ленивая загрузка настроек без побочных эффектов при импорте."""
    settings = TelethonSettings()
    logger.debug(f"Telethon настройки загружены: {settings.safe_dict()}")
    return settings
