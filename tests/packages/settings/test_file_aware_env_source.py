from pathlib import Path

import pytest
from pydantic import Field

from packages.common_settings.base import BaseAppSettings


class DummySettings(BaseAppSettings):
    """Упрощённая модель для проверки FileAwareEnvSource через BaseAppSettings.

    Важно: alias совпадает с именем ENV-переменной.
    """

    simple: str = Field(alias="SIMPLE")
    list_value: list[str] = Field(default_factory=list, alias="LIST_VALUE")
    optional_value: str | None = Field(default=None, alias="OPTIONAL_VALUE")


class TestFileAwareEnvSource:
    def test_simple_value_read_from_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Если SIMPLE_FILE задан и файл существует — значение читается из файла."""

        monkeypatch.delenv("SIMPLE", raising=False)
        monkeypatch.delenv("SIMPLE_FILE", raising=False)

        secret_file: Path = tmp_path / "simple.txt"
        secret_file.write_text("from_file\n", encoding="utf-8")

        monkeypatch.setenv("SIMPLE_FILE", str(secret_file))

        settings = DummySettings()

        assert settings.simple == "from_file"

    def test_missing_file_raises_value_error_for_required_field(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Если SIMPLE_FILE указывает на несуществующий файл — получаем ValueError при загрузке настроек."""

        monkeypatch.delenv("SIMPLE", raising=False)
        monkeypatch.delenv("SIMPLE_FILE", raising=False)

        missing_path: Path = tmp_path / "no_such_file.txt"
        monkeypatch.setenv("SIMPLE_FILE", str(missing_path))

        with pytest.raises(ValueError) as exc_info:
            DummySettings()

        cause = exc_info.value.__cause__
        assert isinstance(cause, ValueError)
        assert "points to missing file" in str(cause)

    def test_missing_file_for_optional_field_also_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Даже для optional-поля *_FILE ссылающийся на несуществующий файл должен привести к ValueError.

        Это важно, чтобы явно подсветить ошибку конфигурации, а не молча подставить None.
        """

        monkeypatch.delenv("OPTIONAL_VALUE", raising=False)
        monkeypatch.delenv("OPTIONAL_VALUE_FILE", raising=False)

        missing_path: Path = tmp_path / "no_such_optional.txt"
        monkeypatch.setenv("OPTIONAL_VALUE_FILE", str(missing_path))

        with pytest.raises(ValueError) as exc_info:
            DummySettings()

        cause = exc_info.value.__cause__
        assert isinstance(cause, ValueError)
        assert "points to missing file" in str(cause)

    def test_list_value_read_from_json_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # SIMPLE обязателен, поэтому подставляем любое валидное значение,
        # чтобы сосредоточиться на проверке LIST_VALUE_FILE.
        monkeypatch.setenv("SIMPLE", "dummy")
        monkeypatch.delenv("SIMPLE_FILE", raising=False)

        monkeypatch.delenv("LIST_VALUE", raising=False)
        monkeypatch.delenv("LIST_VALUE_FILE", raising=False)

        file_content = '["a", "b", "c"]'
        secret_file: Path = tmp_path / "list.json"
        secret_file.write_text(file_content, encoding="utf-8")

        monkeypatch.setenv("LIST_VALUE_FILE", str(secret_file))

        settings = DummySettings()

        assert settings.list_value == ["a", "b", "c"]

    def test_string_field_not_treated_as_json(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Для обычного str-поля содержимое файла не пытаются парсить как JSON."""

        monkeypatch.delenv("SIMPLE", raising=False)
        monkeypatch.delenv("SIMPLE_FILE", raising=False)

        secret_file: Path = tmp_path / "simple_raw.txt"
        secret_file.write_text("not,a,json,list", encoding="utf-8")

        monkeypatch.setenv("SIMPLE_FILE", str(secret_file))

        settings = DummySettings()

        assert settings.simple == "not,a,json,list"

    def test_env_value_takes_priority_over_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Если ENV задан, *_FILE не используется."""

        secret_file: Path = tmp_path / "simple.txt"
        secret_file.write_text("from_file\n", encoding="utf-8")

        monkeypatch.setenv("SIMPLE", "from_env")
        monkeypatch.setenv("SIMPLE_FILE", str(secret_file))

        settings = DummySettings()

        assert settings.simple == "from_env"

    def test_empty_env_falls_back_to_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Пустая строка в ENV должна дать fallback на *_FILE."""

        secret_file: Path = tmp_path / "simple.txt"
        secret_file.write_text("from_file\n", encoding="utf-8")

        monkeypatch.setenv("SIMPLE", "")
        monkeypatch.setenv("SIMPLE_FILE", str(secret_file))

        settings = DummySettings()

        assert settings.simple == "from_file"

    def test_list_value_csv_string_parsed_to_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CSV-строка должна превратиться в list[str] для list-поля."""

        monkeypatch.setenv("SIMPLE", "dummy")
        monkeypatch.delenv("SIMPLE_FILE", raising=False)

        monkeypatch.setenv("LIST_VALUE", "a, b, c")
        monkeypatch.delenv("LIST_VALUE_FILE", raising=False)

        settings = DummySettings()

        assert settings.list_value == ["a", "b", "c"]

    def test_optional_value_is_none_when_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OPTIONAL_VALUE остается None, если ENV и *_FILE не заданы."""

        monkeypatch.setenv("SIMPLE", "dummy")
        monkeypatch.delenv("SIMPLE_FILE", raising=False)

        monkeypatch.delenv("OPTIONAL_VALUE", raising=False)
        monkeypatch.delenv("OPTIONAL_VALUE_FILE", raising=False)

        settings = DummySettings()

        assert settings.optional_value is None

    def test_empty_file_value_kept_as_empty_string(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Пустой файл дает пустую строку для обязательного поля."""

        secret_file: Path = tmp_path / "simple_empty.txt"
        secret_file.write_text("\n", encoding="utf-8")

        monkeypatch.delenv("SIMPLE", raising=False)
        monkeypatch.setenv("SIMPLE_FILE", str(secret_file))

        settings = DummySettings()

        assert settings.simple == ""
