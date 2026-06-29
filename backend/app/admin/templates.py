"""Singleton Jinja2Templates для admin."""

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="backend/web/templates/admin")
