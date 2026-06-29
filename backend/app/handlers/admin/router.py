"""Главный роутер admin. Только монтирование view-роутеров."""

from fastapi import APIRouter

from backend.app.handlers.admin.views import (
    auth,
    broadcast,
    categories,
    dashboard,
    ingredients,
    recipes,
    redis_keys,
    tools,
    users,
)

router = APIRouter(prefix="/admin")

router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(recipes.router)
router.include_router(users.router)
router.include_router(categories.router)
router.include_router(ingredients.router)
router.include_router(broadcast.router)
router.include_router(redis_keys.router)
router.include_router(tools.router)
