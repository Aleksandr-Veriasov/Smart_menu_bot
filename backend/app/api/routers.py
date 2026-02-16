from fastapi import APIRouter

from backend.app.api.broadcast_admin import broadcast_admin_router
from backend.app.api.webapp import webapp_router

api_router = APIRouter()

# Telegram WebApp API
api_router.include_router(webapp_router, prefix="/webapp", tags=["webapp"])

# Admin-only Broadcast API (session-based auth)
api_router.include_router(broadcast_admin_router, prefix="/broadcast-admin", tags=["broadcast-admin"])
