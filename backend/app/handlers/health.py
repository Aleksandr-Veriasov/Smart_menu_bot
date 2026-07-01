"""Health-check для Docker HEALTHCHECK и внешних проверок доступности."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/ping", include_in_schema=False)
async def ping() -> dict[str, bool]:
    return {"ok": True}
