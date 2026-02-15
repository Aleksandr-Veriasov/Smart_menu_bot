from fastapi import FastAPI

from backend.app.api.routers import api_router


def setup_routes(app: FastAPI) -> None:
    # API
    app.include_router(api_router, prefix="/api")

    # health
    @app.get("/ping", tags=["health"])
    async def ping() -> dict[str, bool]:
        return {"ok": True}
