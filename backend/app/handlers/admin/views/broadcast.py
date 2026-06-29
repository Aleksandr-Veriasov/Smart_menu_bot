"""admin: рассылки — список кампаний, создание/редактирование, список сообщений."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_broadcast_service
from backend.app.core.templates import templates
from packages.enums import (
    BroadcastAudienceType,
    BroadcastCampaignStatus,
    BroadcastMessageStatus,
)
from packages.schemas.broadcast import BroadcastCampaignCreate
from packages.services.broadcast_service import BroadcastService
from packages.utils import parse_datetime_form

router = APIRouter(prefix="/broadcast")

_PAGE_SIZE = 30
_ServiceDep = Annotated[BroadcastService, Depends(get_broadcast_service)]


# ── Кампании ──────────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def campaigns_list(
    request: Request,
    service: _ServiceDep,
    page: int = 1,
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    campaigns, total = await service.list_campaigns_page(page, _PAGE_SIZE)
    return templates.TemplateResponse(
        request,
        "broadcast/campaigns.html",
        {
            "admin_login": current_login(request),
            "campaigns": campaigns,
            "page": page,
            "total": total,
            "total_pages": max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE),
            "statuses": BroadcastCampaignStatus,
        },
    )


@router.get("/new", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def campaign_new_form(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    return templates.TemplateResponse(
        request,
        "broadcast/form.html",
        {
            "admin_login": current_login(request),
            "campaign": None,
            "error": None,
            "audience_types": list(BroadcastAudienceType),
            "statuses": list(BroadcastCampaignStatus),
        },
    )


@router.post("/new", response_model=None, include_in_schema=False)
async def campaign_create(
    request: Request,
    service: _ServiceDep,
    name: str = Form(...),
    status: str = Form("draft"),
    audience_type: str = Form("all_users"),
    text: str = Form(...),
    parse_mode: str = Form("HTML"),
    scheduled_at: str = Form(""),
    photo_file_id: str = Form(""),
    photo_url: str = Form(""),
    reply_markup_json: str = Form(""),
    disable_web_page_preview: bool = Form(True),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect
    name, text = name.strip(), text.strip()
    if not name or not text:
        return templates.TemplateResponse(
            request,
            "broadcast/form.html",
            {
                "admin_login": current_login(request),
                "campaign": None,
                "error": "Название и текст обязательны",
                "audience_types": list(BroadcastAudienceType),
                "statuses": list(BroadcastCampaignStatus),
            },
        )
    await service.create_campaign(
        BroadcastCampaignCreate(
            name=name,
            status=BroadcastCampaignStatus(status),
            audience_type=BroadcastAudienceType(audience_type),
            text=text,
            parse_mode=parse_mode,
            scheduled_at=parse_datetime_form(scheduled_at),
            photo_file_id=photo_file_id.strip() or None,
            photo_url=photo_url.strip() or None,
            reply_markup_json=reply_markup_json.strip() or None,
            disable_web_page_preview=disable_web_page_preview,
        )
    )
    return RedirectResponse(url="/admin/broadcast", status_code=303)


@router.get("/{campaign_id}/edit", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def campaign_edit_form(
    request: Request,
    service: _ServiceDep,
    campaign_id: int,
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        campaign = await service.get_campaign_or_raise(campaign_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return templates.TemplateResponse(
        request,
        "broadcast/form.html",
        {
            "admin_login": current_login(request),
            "campaign": campaign,
            "error": None,
            "audience_types": list(BroadcastAudienceType),
            "statuses": list(BroadcastCampaignStatus),
        },
    )


@router.post("/{campaign_id}/edit", response_model=None, include_in_schema=False)
async def campaign_update(
    request: Request,
    service: _ServiceDep,
    campaign_id: int,
    name: str = Form(...),
    status: str = Form("draft"),
    audience_type: str = Form("all_users"),
    text: str = Form(...),
    parse_mode: str = Form("HTML"),
    scheduled_at: str = Form(""),
    photo_file_id: str = Form(""),
    photo_url: str = Form(""),
    reply_markup_json: str = Form(""),
    disable_web_page_preview: bool = Form(True),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect
    name, text = name.strip(), text.strip()
    if not name or not text:
        try:
            campaign = await service.get_campaign_or_raise(campaign_id)
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
        return templates.TemplateResponse(
            request,
            "broadcast/form.html",
            {
                "admin_login": current_login(request),
                "campaign": campaign,
                "error": "Название и текст обязательны",
                "audience_types": list(BroadcastAudienceType),
                "statuses": list(BroadcastCampaignStatus),
            },
        )
    try:
        await service.admin_update_campaign(
            campaign_id,
            name=name,
            status=status,
            audience_type=audience_type,
            text=text,
            parse_mode=parse_mode,
            scheduled_at=parse_datetime_form(scheduled_at),
            photo_file_id=photo_file_id.strip() or None,
            photo_url=photo_url.strip() or None,
            reply_markup_json=reply_markup_json.strip() or None,
            disable_web_page_preview=disable_web_page_preview,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return RedirectResponse(url="/admin/broadcast", status_code=303)


@router.post("/{campaign_id}/queue", response_model=None, include_in_schema=False)
async def campaign_queue(request: Request, service: _ServiceDep, campaign_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        await service.queue_campaign(campaign_id)
    except (LookupError, ValueError):
        pass
    return RedirectResponse(url="/admin/broadcast", status_code=303)


@router.post("/{campaign_id}/pause", response_model=None, include_in_schema=False)
async def campaign_pause(request: Request, service: _ServiceDep, campaign_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        await service.pause_campaign(campaign_id)
    except (LookupError, ValueError):
        pass
    return RedirectResponse(url="/admin/broadcast", status_code=303)


@router.post("/{campaign_id}/resume", response_model=None, include_in_schema=False)
async def campaign_resume(request: Request, service: _ServiceDep, campaign_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        await service.resume_campaign(campaign_id)
    except (LookupError, ValueError):
        pass
    return RedirectResponse(url="/admin/broadcast", status_code=303)


@router.post("/{campaign_id}/cancel", response_model=None, include_in_schema=False)
async def campaign_cancel(request: Request, service: _ServiceDep, campaign_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        await service.cancel_campaign(campaign_id)
    except (LookupError, ValueError):
        pass
    return RedirectResponse(url="/admin/broadcast", status_code=303)


@router.post("/{campaign_id}/delete", response_model=None, include_in_schema=False)
async def campaign_delete(
    request: Request,
    service: _ServiceDep,
    campaign_id: int,
) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    await service.delete_campaign(campaign_id)
    return RedirectResponse(url="/admin/broadcast", status_code=303)


# ── Сообщения кампании ────────────────────────────────────────────────────────


@router.get("/{campaign_id}/messages", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def campaign_messages(
    request: Request,
    service: _ServiceDep,
    campaign_id: int,
    page: int = 1,
    status_filter: str = "",
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    try:
        campaign, messages, total = await service.list_messages_page(campaign_id, page, _PAGE_SIZE, status_filter)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return templates.TemplateResponse(
        request,
        "broadcast/messages.html",
        {
            "admin_login": current_login(request),
            "campaign": campaign,
            "messages": messages,
            "page": page,
            "total": total,
            "total_pages": max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE),
            "status_filter": status_filter,
            "message_statuses": list(BroadcastMessageStatus),
        },
    )
