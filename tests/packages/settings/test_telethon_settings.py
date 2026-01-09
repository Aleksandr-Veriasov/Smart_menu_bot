import pytest

from packages.common_settings.telethon_settings import (
    TelethonSettings,
    get_telethon_settings,
)


class TestTelethonSettings:
    @pytest.fixture(autouse=True)
    def clear_cache(self) -> None:
        """Очищает кэш настроек между тестами."""
        get_telethon_settings.cache_clear()

    def test_defaults_loaded_with_required_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Дефолты применяются, когда заданы только обязательные ENV-переменные."""
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("TG_API_ID", "123")
        monkeypatch.setenv("TG_API_HASH", "hash_value")

        settings = TelethonSettings()

        assert settings.debug is False
        assert settings.session_path == "/app/sessions/user.session"
        assert settings.concurrency == 1
        assert settings.target_bot == "SaveAsBot"
        assert settings.download_dir == "/app/videos"
        assert settings.timeout_sec == 180
        assert settings.edit_timeout_sec == 30
        assert settings.api_id == 123
        assert settings.api_hash.get_secret_value() == "hash_value"

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ENV-значения переопределяют дефолты."""
        monkeypatch.setenv("TG_API_ID", "999")
        monkeypatch.setenv("TG_API_HASH", "hash_value")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("TELETHON_CONCURRENCY", "5")
        monkeypatch.setenv("TELETHON_SESSION_PATH", "/tmp/session")
        monkeypatch.setenv("TELETHON_TARGET_BOT", "OtherBot")
        monkeypatch.setenv("TELETHON_DOWNLOAD_DIR", "/tmp/videos")
        monkeypatch.setenv("TELETHON_TIMEOUT_SEC", "42")
        monkeypatch.setenv("TELETHON_EDIT_TIMEOUT_SEC", "7")

        settings = TelethonSettings()

        assert settings.debug is True
        assert settings.concurrency == 5
        assert settings.session_path == "/tmp/session"
        assert settings.target_bot == "OtherBot"
        assert settings.download_dir == "/tmp/videos"
        assert settings.timeout_sec == 42
        assert settings.edit_timeout_sec == 7

    def test_safe_dict_masks_api_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """safe_dict скрывает секретное значение, сохраняя остальные поля."""
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("TG_API_ID", "123")
        monkeypatch.setenv("TG_API_HASH", "super_secret")

        settings = TelethonSettings()
        safe = settings.safe_dict()

        assert safe["api_hash"] == "***"
        assert safe["api_id"] == 123
        assert safe["debug"] is False

    def test_get_telethon_settings_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_telethon_settings возвращает кэшированный экземпляр."""
        monkeypatch.setenv("TG_API_ID", "123")
        monkeypatch.setenv("TG_API_HASH", "hash_value")

        first = get_telethon_settings()
        second = get_telethon_settings()

        assert first is second
