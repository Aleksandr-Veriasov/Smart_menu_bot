from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.admin_v2.deps import check_auth, current_login
from backend.app.admin_v2.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect
    return templates.TemplateResponse(request, "dashboard.html", {"admin_login": current_login(request)})
