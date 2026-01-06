import json
import os
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import EnvSettingsSource, PydanticBaseSettingsSource


class FileAwareEnvSource(EnvSettingsSource):
    """
    Источник ENV с поддержкой fallback на <ENV>_FILE.
    Приоритет: ENV > ENV_FILE.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # 1) Берём стандартное значение из окружения
        value, key, is_complex = super().get_field_value(field, field_name)

        # 2) Если пусто — пробуем <KEY>_FILE
        if value in (None, ""):
            file_env = f"{key}_FILE"  # key уже учитывает env_prefix и alias
            file_path = os.getenv(file_env)
            if file_path:
                p = Path(file_path).expanduser().resolve()
                if not p.is_file():
                    raise ValueError(f"{file_env} points to missing file: {p}")
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
            is_list_of_str = (origin in (list, tuple)) and (len(args) == 1 and args[0] is str)

            # строка 'не похожа' на JSON?
            looks_like_json = (
                s.startswith("[")
                or s.startswith("{")
                or s.startswith('"')
                or s in ("null", "true", "false")
                or (s and s[0] in "-0123456789")
            )

            if is_list_of_str and not looks_like_json:
                # Превратим 'a,b,c' → ['a','b','c'] и оставим is_complex=True
                parts = [x.strip() for x in s.split(",") if x.strip()]
                value = json.dumps(parts)
                is_complex = True  # пусть pydantic сам json.loads(...) сделает

        return value, key, is_complex


class BaseAppSettings(BaseSettings):
    """Базовый класс настроек приложения с кастомным источником ENV.
    Используется для переопределения источников конфигурации и
    настройки их порядка.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
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
    ) -> tuple[
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
            file_secret_settings,
        )
