import asyncio
import logging
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import AnyUrl, BaseModel

from packages.common_settings.telethon_settings import get_telethon_settings
from packages.logging_config import setup_logging
from telethon_worker import telethon_client

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

        async with telethon_client.sem:
            try:
                # Conversation: отправили ссылку -> читаем ответы, пока не прилетит видео
                async with telethon_client.client.conversation(target_bot, timeout=timeout_sec) as conv:
                    await conv.send_message(str(payload.url))
                    logger.info(f"Ссылка отправлена боту: url={payload.url} target_bot={target_bot}")

                    video_path = None
                    video_caption = ""

                    # 1) Wait for the video
                    while True:
                        msg = await conv.get_response()
                        logger.info("Получено сообщение от бота")
                        if telethon_client.is_video_message(msg):
                            video_caption = msg.message or ""
                            video_path = await msg.download_media(file=download_dir)
                            if not video_path:
                                raise RuntimeError("download_media() returned empty path")
                            logger.info(f"Видео скачано: video_path={video_path}")
                            break

                    # 2) Нажимаем кнопку "получить текст поста" (она приходит отдельным сообщением после видео)
                    desired_button_text = "получить текст поста"
                    description = ""
                    edit_timeout_sec = settings.edit_timeout_sec

                    logger.info(f"Ищу кнопку получения текста поста: button_text={desired_button_text}")

                    button_msg = None
                    button_coords = None

                    # Ждем следующее сообщение(я) от SaveAsBot, пока не увидим inline-кнопку
                    while True:
                        msg = await conv.get_response()
                        logger.info("Получено сообщение от бота (поиск кнопки текста поста)")
                        coords = telethon_client.find_button_coords(msg, desired_button_text)
                        if coords:
                            button_msg = msg
                            button_coords = coords
                            break

                    # Важно: SaveAsBot после клика обычно НЕ присылает новое сообщение,
                    # а РЕДАКТИРУЕТ то же сообщение с кнопкой. Поэтому ждём edit.
                    assert button_msg is not None and button_coords is not None
                    edit_task = asyncio.create_task(
                        telethon_client.wait_for_message_edit(
                            telethon_client.client,
                            target_bot,
                            button_msg.id,
                            timeout_sec=edit_timeout_sec,
                        )
                    )

                    await button_msg.click(*button_coords)
                    logger.info(
                        f"Нажала кнопку получения текста поста: "
                        f"coords={button_coords} button_msg_id={button_msg.id}"
                    )

                    edited = await edit_task
                    logger.info("Сообщение отредактировано ботом")

                    text = (edited.message or "").strip()
                    if text:
                        description = text
                        logger.info(f"Получен текст поста: description_len={len(description)}")

                    final_description = description or video_caption
                    logger.info(
                        f"Возвращаю результат: "
                        f"video_path={video_path} "
                        f"caption={video_caption} "
                        f"description={final_description} "
                        f"used={'post_text' if description else 'caption'}"
                    )
                    return DownloadOut(file_path=str(video_path), description=final_description)

            except asyncio.TimeoutError as exc:
                logger.warning(f"Таймаут ожидания ответа от SaveAsBot: url={payload.url}")
                raise HTTPException(status_code=504, detail="Timeout waiting SaveAsBot video") from exc
            except Exception as e:
                logger.exception(f"Ошибка сценария SaveAsBot: url={payload.url}")
                raise HTTPException(status_code=500, detail=f"SaveAsBot flow failed: {e}") from e

    return app


app = get_app()
