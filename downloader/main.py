from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from downloader.video_service import download_video

logging.basicConfig(
    level=os.getenv('DOWNLOADER_LOG_LEVEL', 'DEBUG'),
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
)
logger = logging.getLogger(__name__)


class DownloadRequest(BaseModel):
    url: HttpUrl = Field(
        ...,
        description='Ссылка на Instagram, TikTok, Pinterest или YouTube Shorts видео',
    )


class DownloadResponse(BaseModel):
    file_path: str
    description: str


@lru_cache
def get_app() -> FastAPI:
    app = FastAPI(
        title='Media Downloader',
        description='Сервис для скачивания Instagram/TikTok/Pinterest/YouTube Shorts через Playwright',
        version='0.1.0',
    )

    @app.get('/health', tags=['system'])
    async def healthcheck() -> dict:
        return {'status': 'ok'}

    @app.post('/download', response_model=DownloadResponse, tags=['downloader'])
    async def download(payload: DownloadRequest) -> DownloadResponse:
        logger.info(f'Получен запрос на скачивание: {payload.url}')
        try:
            file_path, caption = await asyncio.to_thread(
                download_video, str(payload.url)
            )
        except ValueError as exc:
            logger.warning(f'Некорректный запрос: {exc}')
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception(f'Ошибка загрузки через Playwright: {exc}')
            raise HTTPException(status_code=500, detail='Playwright download failed') from exc

        return DownloadResponse(file_path=file_path, description=caption or '')

    return app


app = get_app()
