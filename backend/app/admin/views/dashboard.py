from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.admin.deps import check_auth, current_login, get_db, get_redis
from backend.app.admin.templates import templates
from packages.services.admin_service import AdminService

router = APIRouter()


@router.get("/", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    stats = await AdminService(get_db(request), get_redis(request)).get_stats()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"admin_login": current_login(request), "stats": stats},
    )
