from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from packages.db.models import BroadcastAudienceType, BroadcastCampaignStatus


def _coerce_utc(dt: datetime) -> datetime:
    # Store in UTC; if naive assume UTC.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class BroadcastCampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    text: str = Field(..., min_length=1)
    scheduled_at: datetime | None = None
    status: BroadcastCampaignStatus = BroadcastCampaignStatus.draft
    audience_type: BroadcastAudienceType = BroadcastAudienceType.all_users
    audience_params_json: str | None = None

    parse_mode: str = "HTML"
    disable_web_page_preview: bool = True
    reply_markup_json: str | None = None
    photo_file_id: str | None = None
    photo_url: str | None = None

    @field_validator("scheduled_at")
    @classmethod
    def _validate_scheduled_at(cls, v: datetime | None) -> datetime | None:
        return _coerce_utc(v) if v is not None else None

    @field_validator("reply_markup_json")
    @classmethod
    def _validate_reply_markup(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        try:
            obj = json.loads(v)
        except Exception as e:
            raise ValueError(f"reply_markup_json must be valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("reply_markup_json must be a JSON object (as in Telegram Bot API)")
        return v


class BroadcastCampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    text: str | None = Field(default=None, min_length=1)
    scheduled_at: datetime | None = None
    status: BroadcastCampaignStatus | None = None

    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    reply_markup_json: str | None = None
    photo_file_id: str | None = None
    photo_url: str | None = None

    @field_validator("scheduled_at")
    @classmethod
    def _validate_scheduled_at(cls, v: datetime | None) -> datetime | None:
        return _coerce_utc(v) if v is not None else None

    @field_validator("reply_markup_json")
    @classmethod
    def _validate_reply_markup(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.strip():
            return None
        try:
            obj = json.loads(v)
        except Exception as e:
            raise ValueError(f"reply_markup_json must be valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("reply_markup_json must be a JSON object (as in Telegram Bot API)")
        return v


class BroadcastCampaignRead(BaseModel):
    id: int
    name: str
    status: BroadcastCampaignStatus
    audience_type: BroadcastAudienceType
    audience_params_json: str | None
    text: str
    parse_mode: str
    disable_web_page_preview: bool
    reply_markup_json: str | None
    photo_file_id: str | None
    photo_url: str | None
    scheduled_at: datetime | None
    created_at: datetime
    outbox_created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    total_recipients: int | None
    sent_count: int
    failed_count: int
    last_error: str | None

    class Config:
        from_attributes = True


class BroadcastAction(BaseModel):
    status: BroadcastCampaignStatus


class BroadcastMessageRead(BaseModel):
    id: int
    campaign_id: int
    chat_id: int
    status: Any
    attempts: int
    next_retry_at: datetime | None
    locked_until: datetime | None
    created_at: datetime
    sent_at: datetime | None
    last_error: str | None

    class Config:
        from_attributes = True
