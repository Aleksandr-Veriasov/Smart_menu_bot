"""admin_v2: рассылки — список кампаний, создание/редактирование, список сообщений."""

from datetime import UTC

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from backend.app.admin_v2.deps import check_auth, current_login
from backend.app.admin_v2.templates import templates
from backend.app.utils.fastapi_state import get_backend_db
from packages.db.models.broadcast import (
    BroadcastAudienceType,
    BroadcastCampaign,
    BroadcastCampaignStatus,
    BroadcastMessage,
)

router = APIRouter()

_PAGE_SIZE = 30


# ── Кампании ──────────────────────────────────────────────────────────────────


@router.get("/broadcast", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def campaigns_list(request: Request, page: int = 1) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    offset = (page - 1) * _PAGE_SIZE

    async with db.session() as session:
        total: int = (await session.execute(select(func.count(BroadcastCampaign.id)))).scalar_one()

        result = await session.execute(
            select(BroadcastCampaign).order_by(BroadcastCampaign.id.desc()).offset(offset).limit(_PAGE_SIZE)
        )
        campaigns = result.scalars().all()

    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    return templates.TemplateResponse(
        request,
        "broadcast/campaigns.html",
        {
            "admin_login": current_login(request),
            "campaigns": campaigns,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "statuses": BroadcastCampaignStatus,
        },
    )


@router.get("/broadcast/new", response_class=HTMLResponse, response_model=None, include_in_schema=False)
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


@router.post("/broadcast/new", response_model=None, include_in_schema=False)
async def campaign_create(
    request: Request,
    name: str = Form(...),
    status: str = Form("draft"),
    audience_type: str = Form("all_users"),
    text: str = Form(...),
    parse_mode: str = Form("HTML"),
    scheduled_at: str = Form(""),
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

    from datetime import datetime

    sched = None
    if scheduled_at.strip():
        try:
            sched = datetime.fromisoformat(scheduled_at.strip()).replace(tzinfo=UTC)
        except ValueError:
            pass

    db = get_backend_db(request)
    async with db.session() as session:
        campaign = BroadcastCampaign(
            name=name,
            status=BroadcastCampaignStatus(status),
            audience_type=BroadcastAudienceType(audience_type),
            text=text,
            parse_mode=parse_mode,
            scheduled_at=sched,
        )
        session.add(campaign)

    return RedirectResponse(url="/admin_v2/broadcast", status_code=303)


@router.get("/broadcast/{campaign_id}/edit", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def campaign_edit_form(request: Request, campaign_id: int) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        campaign = await session.get(BroadcastCampaign, campaign_id)

    if campaign is None:
        return RedirectResponse(url="/admin_v2/broadcast", status_code=303)

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


@router.post("/broadcast/{campaign_id}/edit", response_model=None, include_in_schema=False)
async def campaign_update(
    request: Request,
    campaign_id: int,
    name: str = Form(...),
    status: str = Form("draft"),
    audience_type: str = Form("all_users"),
    text: str = Form(...),
    parse_mode: str = Form("HTML"),
    scheduled_at: str = Form(""),
) -> RedirectResponse | HTMLResponse:
    if redirect := check_auth(request):
        return redirect

    name, text = name.strip(), text.strip()
    if not name or not text:
        db = get_backend_db(request)
        async with db.session() as session:
            campaign = await session.get(BroadcastCampaign, campaign_id)
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

    from datetime import datetime

    sched = None
    if scheduled_at.strip():
        try:
            sched = datetime.fromisoformat(scheduled_at.strip()).replace(tzinfo=UTC)
        except ValueError:
            pass

    db = get_backend_db(request)
    async with db.session() as session:
        campaign = await session.get(BroadcastCampaign, campaign_id)
        if campaign is None:
            return RedirectResponse(url="/admin_v2/broadcast", status_code=303)
        campaign.name = name
        campaign.status = BroadcastCampaignStatus(status)
        campaign.audience_type = BroadcastAudienceType(audience_type)
        campaign.text = text
        campaign.parse_mode = parse_mode
        campaign.scheduled_at = sched

    return RedirectResponse(url="/admin_v2/broadcast", status_code=303)


@router.post("/broadcast/{campaign_id}/delete", response_model=None, include_in_schema=False)
async def campaign_delete(request: Request, campaign_id: int) -> RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        campaign = await session.get(BroadcastCampaign, campaign_id)
        if campaign:
            await session.delete(campaign)

    return RedirectResponse(url="/admin_v2/broadcast", status_code=303)


# ── Сообщения кампании ────────────────────────────────────────────────────────


@router.get(
    "/broadcast/{campaign_id}/messages", response_class=HTMLResponse, response_model=None, include_in_schema=False
)
async def campaign_messages(
    request: Request,
    campaign_id: int,
    page: int = 1,
    status_filter: str = "",
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    offset = (page - 1) * _PAGE_SIZE

    async with db.session() as session:
        campaign = await session.get(BroadcastCampaign, campaign_id)
        if campaign is None:
            return RedirectResponse(url="/admin_v2/broadcast", status_code=303)

        base = select(BroadcastMessage).where(BroadcastMessage.campaign_id == campaign_id)
        if status_filter:
            base = base.where(BroadcastMessage.status == status_filter)

        total: int = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

        result = await session.execute(base.order_by(BroadcastMessage.id.desc()).offset(offset).limit(_PAGE_SIZE))
        messages = result.scalars().all()

    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    return templates.TemplateResponse(
        request,
        "broadcast/messages.html",
        {
            "admin_login": current_login(request),
            "campaign": campaign,
            "messages": messages,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "status_filter": status_filter,
            "message_statuses": (
                list(BroadcastMessage.__table__.c.status.type.enums)
                if hasattr(BroadcastMessage.__table__.c.status.type, "enums")
                else []
            ),
        },
    )
