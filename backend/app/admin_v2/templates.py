"""Singleton Jinja2Templates для admin_v2."""

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="backend/web/templates/admin_v2")
