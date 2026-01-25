import asyncio
import logging
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import AnyUrl, BaseModel

from packages.common_settings.telethon_settings import get_telethon_settings
from packages.logging_config import setup_logging
from telethon_worker import telethon_client
from telethon_worker.download_flow import download_via_saveasbot

setup_logging()
logger = logging.getLogger(__name__)


class DownloadIn(BaseModel):
    url: AnyUrl


class DownloadOut(BaseModel):
    file_path: str
    description: str = ""


@lru_cache
def get_app() -> FastAPI:
    app = FastAPI(lifespan=telethon_client.lifespan)
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.get("/health", tags=["healthy"])
    async def healthcheck() -> dict:
        if not telethon_client.client or not telethon_client.sem:
            raise HTTPException(status_code=503, detail="Telethon client is not ready")
        return {"status": "ok"}

    @app.post("/download", response_model=DownloadOut)
    async def download(payload: DownloadIn):
        if not telethon_client.client or not telethon_client.sem:
            raise HTTPException(status_code=503, detail="Telethon client is not ready")

        settings = get_telethon_settings()
        target_bot = settings.target_bot
        download_dir = settings.download_dir
        timeout_sec = settings.timeout_sec

        logger.info(
            f"Получен запрос на скачивание: url={payload.url} target_bot={target_bot} download_dir={download_dir} "
            f"timeout_sec={timeout_sec}"
        )

        try:
            file_path, description = await download_via_saveasbot(
                str(payload.url),
                target_bot=target_bot,
                download_dir=download_dir,
                timeout_sec=timeout_sec,
                edit_timeout_sec=settings.edit_timeout_sec,
            )
            return DownloadOut(file_path=file_path, description=description)

        except asyncio.TimeoutError as exc:
            logger.warning(f"Таймаут ожидания ответа от SaveAsBot: url={payload.url}")
            raise HTTPException(status_code=504, detail="Timeout waiting SaveAsBot video") from exc
        except Exception as e:
            logger.exception(f"Ошибка сценария SaveAsBot: url={payload.url}")
            raise HTTPException(status_code=500, detail=f"SaveAsBot flow failed: {e}") from e

    return app


app = get_app()
