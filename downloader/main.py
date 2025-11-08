from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from downloader.playwright_service import download_instagram_with_playwright

logging.basicConfig(
    level=os.getenv("DOWNLOADER_LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


class DownloadRequest(BaseModel):
    url: HttpUrl = Field(..., description="Ссылка на Instagram пост или Reels")


class DownloadResponse(BaseModel):
    file_path: str
    description: str


@lru_cache
def get_app() -> FastAPI:
    app = FastAPI(
        title="Instagram Downloader",
        description="Сервис для скачивания Instagram-видео через Playwright",
        version="0.1.0",
    )

    @app.get("/health", tags=["system"])
    async def healthcheck() -> dict:
        return {"status": "ok"}

    @app.post("/download", response_model=DownloadResponse, tags=["downloader"])
    async def download(payload: DownloadRequest) -> DownloadResponse:
        logger.info("Получен запрос на скачивание: %s", payload.url)
        try:
            file_path, caption = await asyncio.to_thread(
                download_instagram_with_playwright, str(payload.url)
            )
        except ValueError as exc:
            logger.warning("Некорректный запрос: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Ошибка загрузки через Playwright: %s", exc)
            raise HTTPException(status_code=500, detail="Playwright download failed") from exc

        return DownloadResponse(file_path=file_path, description=caption or "")

    return app


app = get_app()
