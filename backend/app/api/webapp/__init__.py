from fastapi import APIRouter

from backend.app.api.webapp import categories, recipes

webapp_router = APIRouter()
webapp_router.include_router(categories.router)
webapp_router.include_router(recipes.router)

__all__ = ["webapp_router"]
