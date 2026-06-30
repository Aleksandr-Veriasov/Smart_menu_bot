from fastapi import APIRouter

from backend.app.api.webapp import categories, recipes

router = APIRouter(prefix="/api/webapp")

router.include_router(categories.router)
router.include_router(recipes.router)
