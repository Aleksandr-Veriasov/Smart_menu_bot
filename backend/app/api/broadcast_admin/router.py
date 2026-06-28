from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import get_broadcast_service, require_admin
from packages.schemas import (
    BroadcastCampaignCreate,
    BroadcastCampaignRead,
    BroadcastCampaignUpdate,
    BroadcastMessageRead,
)
from packages.services import BroadcastService

broadcast_admin_router = APIRouter(dependencies=[Depends(require_admin)])

Service = Annotated[BroadcastService, Depends(get_broadcast_service)]


@broadcast_admin_router.get("/campaigns", response_model=list[BroadcastCampaignRead])
async def list_campaigns(service: Service, limit: int = 50) -> list[BroadcastCampaignRead]:
    return await service.list_campaigns(limit=limit)


@broadcast_admin_router.post("/campaigns", response_model=BroadcastCampaignRead)
async def create_campaign(payload: BroadcastCampaignCreate, service: Service) -> BroadcastCampaignRead:
    return await service.create_campaign(payload)


@broadcast_admin_router.patch("/campaigns/{campaign_id}", response_model=BroadcastCampaignRead)
async def update_campaign(
    campaign_id: int, payload: BroadcastCampaignUpdate, service: Service
) -> BroadcastCampaignRead:
    try:
        return await service.update_campaign(campaign_id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/queue", response_model=BroadcastCampaignRead)
async def queue_campaign(campaign_id: int, service: Service) -> BroadcastCampaignRead:
    try:
        return await service.queue_campaign(campaign_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/pause", response_model=BroadcastCampaignRead)
async def pause_campaign(campaign_id: int, service: Service) -> BroadcastCampaignRead:
    try:
        return await service.pause_campaign(campaign_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/resume", response_model=BroadcastCampaignRead)
async def resume_campaign(campaign_id: int, service: Service) -> BroadcastCampaignRead:
    try:
        return await service.resume_campaign(campaign_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@broadcast_admin_router.post("/campaigns/{campaign_id}/cancel", response_model=BroadcastCampaignRead)
async def cancel_campaign(campaign_id: int, service: Service) -> BroadcastCampaignRead:
    try:
        return await service.cancel_campaign(campaign_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@broadcast_admin_router.get("/campaigns/{campaign_id}/messages", response_model=list[BroadcastMessageRead])
async def list_messages(campaign_id: int, service: Service, limit: int = 200) -> list[BroadcastMessageRead]:
    return await service.list_messages(campaign_id, limit=limit)
