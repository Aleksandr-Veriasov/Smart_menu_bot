from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import func, select

from backend.app.api.routers import api_router
from backend.app.broadcast.page import setup_broadcast_page
from backend.app.utils.fastapi_state import get_backend_db
from packages.db.models import BroadcastCampaign, BroadcastCampaignStatus, Recipe, User


def setup_routes(app: FastAPI) -> None:
    # API
    app.include_router(api_router, prefix="/api")

    # Admin-only broadcast UI
    setup_broadcast_page(app)

    # health
    @app.get("/ping", tags=["health"])
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/admin/stats", tags=["admin"])
    async def admin_stats(request: Request) -> dict[str, int]:
        if "admin_login" not in request.session:
            raise HTTPException(status_code=401, detail="Not authenticated")

        db = get_backend_db(request)
        async with db.session() as session:
            users_count = int((await session.execute(select(func.count(User.id)))).scalar() or 0)
            recipes_count = int((await session.execute(select(func.count(Recipe.id)))).scalar() or 0)
            # Таблицы рассылок могут отсутствовать до применения миграции.
            try:
                broadcasts_count = int((await session.execute(select(func.count(BroadcastCampaign.id)))).scalar() or 0)
                active_broadcasts_count = int(
                    (
                        await session.execute(
                            select(func.count(BroadcastCampaign.id)).where(
                                BroadcastCampaign.status == BroadcastCampaignStatus.running
                            )
                        )
                    ).scalar()
                    or 0
                )
            except Exception:
                broadcasts_count = 0
                active_broadcasts_count = 0

        return {
            "users_count": users_count,
            "recipes_count": recipes_count,
            "broadcasts_count": broadcasts_count,
            "active_broadcasts_count": active_broadcasts_count,
        }
