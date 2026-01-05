import logging
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from downloader.telethon_service import download_video_via_telethon, telethon_base_url
from downloader.video_service import download_video
from packages.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


class DownloadRequest(BaseModel):
    url: HttpUrl = Field(
        ...,
        description="Ссылка на Instagram, TikTok, Pinterest или YouTube Shorts видео",
    )


class DownloadResponse(BaseModel):
    file_path: str
    description: str


@lru_cache
def get_app() -> FastAPI:
    app = FastAPI(
        title="Media Downloader",
        description="Сервис для скачивания Instagram/TikTok/Pinterest/YouTube Shorts",
        version="0.1.0",
    )

    @app.get("/health", tags=["system"])
    async def healthcheck() -> dict:
        return {"status": "ok"}

    @app.post("/download", response_model=DownloadResponse, tags=["downloader"])
    async def download(payload: DownloadRequest) -> DownloadResponse:
        logger.info(f"Получен запрос на скачивание: {payload.url}")

        try:
            file_path, caption = await download_video(str(payload.url))
            return DownloadResponse(file_path=file_path, description=caption or "")
        except ValueError as exc:
            logger.warning(f"Некорректный запрос: {exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as primary_exc:
            logger.warning(
                "Ошибка загрузки через downloader, пробуем fallback",
                exc_info=primary_exc,
            )

            if telethon_base_url():
                logger.info("Пробуем скачать через Telethon worker (SaveAsBot)")
                try:
                    file_path, caption = await download_video_via_telethon(str(payload.url))
                    logger.info("Успешно скачано через Telethon worker")
                    return DownloadResponse(file_path=file_path, description=caption or "")
                except Exception as telethon_exc:
                    logger.exception(f"Ошибка загрузки через Telethon worker: {telethon_exc}")
                    raise HTTPException(
                        status_code=500, detail="Downloader and Telethon worker failed"
                    ) from telethon_exc

            raise HTTPException(status_code=500, detail="Downloader failed") from primary_exc

    return app


app = get_app()
