from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.core.deps import check_auth, current_login, get_admin_service
from backend.app.core.templates import templates
from packages.services.admin_service import AdminService

router = APIRouter()

_ServiceDep = Annotated[AdminService, Depends(get_admin_service)]


@router.get("/", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dashboard(request: Request, service: _ServiceDep) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    stats = await service.get_stats()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"admin_login": current_login(request), "stats": stats},
    )
