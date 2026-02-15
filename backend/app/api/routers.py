from fastapi import APIRouter

from backend.app.api.webapp import webapp_router

api_router = APIRouter()

# Telegram WebApp API
api_router.include_router(webapp_router, prefix="/webapp", tags=["webapp"])
