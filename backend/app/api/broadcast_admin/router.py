from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from backend.app.api.broadcast_admin.schemas import (
    BroadcastCampaignCreate,
    BroadcastCampaignRead,
    BroadcastCampaignUpdate,
    BroadcastMessageRead,
)
from backend.app.utils.fastapi_state import get_backend_db
from packages.db.repository import BroadcastRepository

logger = logging.getLogger(__name__)

broadcast_admin_router = APIRouter()


def _require_admin(request: Request) -> None:
    if "admin_login" not in request.session:
        raise HTTPException(status_code=401, detail="Not authenticated")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@broadcast_admin_router.get("/campaigns", response_model=list[BroadcastCampaignRead])
async def list_campaigns(request: Request, limit: int = 50) -> list[BroadcastCampaignRead]:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        items = await BroadcastRepository.list_campaigns(session, limit=limit)
        return [BroadcastCampaignRead.model_validate(x) for x in items]


@broadcast_admin_router.post("/campaigns", response_model=BroadcastCampaignRead)
async def create_campaign(request: Request, payload: BroadcastCampaignCreate) -> BroadcastCampaignRead:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        campaign = await BroadcastRepository.create_campaign(
            session,
            name=payload.name,
            status=payload.status,
            audience_type=payload.audience_type,
            audience_params_json=payload.audience_params_json,
            text=payload.text,
            parse_mode=payload.parse_mode,
            disable_web_page_preview=payload.disable_web_page_preview,
            reply_markup_json=payload.reply_markup_json,
            photo_file_id=payload.photo_file_id,
            photo_url=payload.photo_url,
            scheduled_at=payload.scheduled_at,
        )
        return BroadcastCampaignRead.model_validate(campaign)


@broadcast_admin_router.patch("/campaigns/{campaign_id}", response_model=BroadcastCampaignRead)
async def update_campaign(
    request: Request, campaign_id: int, payload: BroadcastCampaignUpdate
) -> BroadcastCampaignRead:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        try:
            campaign = await BroadcastRepository.update_campaign(
                session,
                campaign_id=int(campaign_id),
                changes=payload.model_dump(exclude_unset=True, exclude_none=True),
            )
            return BroadcastCampaignRead.model_validate(campaign)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/queue", response_model=BroadcastCampaignRead)
async def queue_campaign(request: Request, campaign_id: int) -> BroadcastCampaignRead:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        try:
            campaign = await BroadcastRepository.queue_campaign(session, campaign_id=int(campaign_id))
            return BroadcastCampaignRead.model_validate(campaign)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/pause", response_model=BroadcastCampaignRead)
async def pause_campaign(request: Request, campaign_id: int) -> BroadcastCampaignRead:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        try:
            campaign = await BroadcastRepository.pause_campaign(session, campaign_id=int(campaign_id))
            return BroadcastCampaignRead.model_validate(campaign)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/resume", response_model=BroadcastCampaignRead)
async def resume_campaign(request: Request, campaign_id: int) -> BroadcastCampaignRead:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        try:
            campaign = await BroadcastRepository.resume_campaign(
                session,
                campaign_id=int(campaign_id),
                now_utc=_utcnow(),
            )
            return BroadcastCampaignRead.model_validate(campaign)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/cancel", response_model=BroadcastCampaignRead)
async def cancel_campaign(request: Request, campaign_id: int) -> BroadcastCampaignRead:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        try:
            campaign = await BroadcastRepository.cancel_campaign(
                session,
                campaign_id=int(campaign_id),
                now_utc=_utcnow(),
            )
            return BroadcastCampaignRead.model_validate(campaign)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e


@broadcast_admin_router.get("/campaigns/{campaign_id}/messages", response_model=list[BroadcastMessageRead])
async def list_messages(request: Request, campaign_id: int, limit: int = 200) -> list[BroadcastMessageRead]:
    _require_admin(request)
    db = get_backend_db(request)
    async with db.session() as session:
        items = await BroadcastRepository.list_messages(session, campaign_id=int(campaign_id), limit=limit)
        return [BroadcastMessageRead.model_validate(x) for x in items]
