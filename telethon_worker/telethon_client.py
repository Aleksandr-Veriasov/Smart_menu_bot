import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telethon import TelegramClient, events

from packages.common_settings.telethon_settings import get_telethon_settings

logger = logging.getLogger(__name__)


def is_video_message(msg) -> bool:
    if getattr(msg, "video", None):
        return True
    mime = ""
    if getattr(msg, "file", None) is not None:
        mime = getattr(msg.file, "mime_type", "") or ""
    return mime.startswith("video/")


def find_button_coords(msg, target_text: str) -> tuple[int, int] | None:
    """Возвращает (row, col) inline-кнопки, совпадающей по тексту (без учета регистра)."""
    buttons = getattr(msg, "buttons", None)
    if not buttons:
        return None

    target = target_text.strip().lower()
    for r, row in enumerate(buttons):
        for c, btn in enumerate(row):
            text = (getattr(btn, "text", "") or "").strip().lower()
            if text == target:
                return r, c
    return None


async def wait_for_message_edit(
    client: TelegramClient,
    chat: str,
    msg_id: int,
    timeout_sec: float,
):
    """Ждет редактирования сообщения `msg_id` в `chat` и возвращает отредактированное."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    async def _handler(event):
        try:
            if getattr(event, "message", None) and event.message.id == msg_id and not fut.done():
                fut.set_result(event.message)
        except Exception as exc:
            if not fut.done():
                fut.set_exception(exc)

    client.add_event_handler(_handler, events.MessageEdited(chats=chat))
    try:
        return await asyncio.wait_for(fut, timeout=timeout_sec)
    finally:
        client.remove_event_handler(_handler, events.MessageEdited(chats=chat))


client: TelegramClient | None = None
sem: asyncio.Semaphore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan FastAPI (замена устаревших startup/shutdown обработчиков)."""
    global client, sem

    settings = get_telethon_settings()
    if settings.debug:
        logger.info("Telethon клиент отключен (DEBUG=true).")
        yield
        return

    api_id = settings.api_id
    api_hash = settings.api_hash.get_secret_value()
    session_path = settings.session_path

    # SaveAsBot лучше дергать последовательно (он может отвечать несколькими сообщениями)
    sem = asyncio.Semaphore(settings.concurrency)

    client = TelegramClient(session_path, api_id, api_hash)
    # Важно: если сессии нет, здесь будет интерактивный логин
    logger.info(f"Запускаю Telethon-клиент: session_path={session_path} " f"concurrency={settings.concurrency}")
    await client.start()

    try:
        yield
    finally:
        if client:
            logger.info("Останавливаю Telethon-клиент")
            await client.disconnect()
            client = None
        sem = None
