from __future__ import annotations

from typing import Literal, Optional

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    model_validator,
)

from packages.dl_protocol.constants import SCHEMA_VERSION
from packages.dl_protocol.errors import ErrorCode, Stage

# Basic type aliases
Platform = Literal['instagram', 'tiktok']
Method = Literal['ytdlp', 'playwright', 'none']
Source = Literal['mp4', 'm3u8']


class DlTask(BaseModel):
    """
    Сообщение о задаче на скачивание, публикуется в `dl:tasks`.
    """
    job_id: str = Field(min_length=4)
    url: AnyUrl | HttpUrl
    platform: Optional[Platform] = Field(default=None)
    ops: Literal['download+convert'] = Field(default='download+convert')
    requested_at: int
    requested_by: Optional[str] = None
    not_before_ts: Optional[int] = None


class DlDone(BaseModel):
    """
    Результат успешной обработки, публикуется в `dl:done`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    v: str = Field(default=SCHEMA_VERSION)
    job_id: str
    platform: Platform
    method: Method  # how we fetched: ytdlp or playwright
    source: Source  # what original media was: mp4 or m3u8

    # Exactly one of these must be provided
    file_path: Optional[str] = Field(
        default=None, description='Local path, e.g. /videos/<job_id>.mp4'
    )
    file_url: Optional[AnyUrl] = Field(
        default=None, description='Remote/S3/Supabase URL if used'
    )

    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    size_mb: Optional[float] = None

    elapsed_sec: float
    finished_at: int

    @model_validator(mode='after')
    def _validate_location(self) -> DlDone:
        has_path = bool(self.file_path)
        has_url = bool(self.file_url)
        if has_path == has_url:  # both set or both missing
            raise ValueError(
                'Exactly one of file_path or file_url must be provided'
            )
        return self


class DlFailed(BaseModel):
    """
    Сообщение об ошибке, публикуется в `dl:failed`.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    v: str = Field(default=SCHEMA_VERSION)
    job_id: str
    platform: Optional[Platform] = None
    stage: Stage
    method: Method  # 'none' if failure before selecting a method

    error_code: ErrorCode
    error_detail: Optional[str] = None

    attempts: int = Field(
        ge=0, description='How many attempts were made for this job'
    )
    elapsed_sec: float
    finished_at: int

    next_try_ts: Optional[int] = Field(
        default=None, description='Suggested time to retry, epoch seconds'
    )
