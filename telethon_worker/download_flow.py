import asyncio
import logging
import os
import re
import time
from urllib.parse import unquote, urlparse

import requests

from telethon_worker import telethon_client

logger = logging.getLogger(__name__)

_DOWNLOAD_BUTTON_TEXT = "скачать видео"
_LARGE_VIDEO_HINT = "весит более 50 мб"
_UPLOADING_HINT = "ваше видео выгружается"


def _filename_from_headers(headers: dict, fallback_name: str) -> str:
    """Выбирает имя файла из заголовков ответа или использует запасной вариант."""
    content_disposition = headers.get("content-disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, flags=re.IGNORECASE)
    if match:
        return unquote(match.group(1))
    match = re.search(r'filename="?([^";]+)"?', content_disposition, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return fallback_name


def _download_video_from_url(url: str, download_dir: str, timeout_sec: float) -> str:
    """Скачивает файл по прямой ссылке и возвращает путь к сохраненному видео."""
    os.makedirs(download_dir, exist_ok=True)
    parsed = urlparse(url)
    logger.info(f"Скачиваю видео по ссылке: host={parsed.netloc}")
    with requests.get(url, stream=True, timeout=timeout_sec) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        content_length = response.headers.get("content-length")
        if content_length:
            logger.info(f"Размер видео по заголовкам: {content_length} bytes")
        if content_type and not content_type.startswith("video/"):
            logger.warning(f"Неожиданный content-type при скачивании видео: {content_type}")
        fallback_name = os.path.basename(urlparse(url).path)
        if not fallback_name or "." not in fallback_name:
            fallback_name = f"video_{int(time.time() * 1000)}.mp4"
        filename = _filename_from_headers(dict(response.headers), fallback_name)
        file_path = os.path.join(download_dir, filename)
        with open(file_path, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
    return file_path


def _extract_url_from_buttons(msg, target_text: str | None = None) -> str | None:
    """Возвращает URL из inline-кнопок; при target_text ищет точное совпадение по тексту."""
    buttons = getattr(msg, "buttons", None)
    if not buttons:
        return None
    target = target_text.strip().lower() if target_text else None
    for row in buttons:
        for btn in row:
            url = getattr(btn, "url", None)
            if not url:
                continue
            text = (getattr(btn, "text", "") or "").strip().lower()
            if not target or text == target:
                return url
    if target:
        for row in buttons:
            for btn in row:
                url = getattr(btn, "url", None)
                if url:
                    return url
    return None


def _extract_url_from_entities(msg) -> str | None:
    """Возвращает первую URL-ссылку из entities сообщения, игнорируя t.me."""
    text = msg.message or ""
    for entity in getattr(msg, "entities", []) or []:
        url = getattr(entity, "url", None)
        if url and "t.me/" not in url:
            logger.info(f"Найдена URL-ссылка в entity: {url}")
            return url
        offset = getattr(entity, "offset", None)
        length = getattr(entity, "length", None)
        if offset is None or length is None:
            continue
        candidate = text[offset : offset + length]
        if candidate.startswith("http") and "t.me/" not in candidate:
            logger.info(f"Найдена URL-ссылка в тексте по entity: {candidate}")
            return candidate
    return None


def _extract_url_after_anchor(text: str, anchor: str) -> str | None:
    """Ищет первую URL после якоря в тексте."""
    lower = text.lower()
    anchor_pos = lower.find(anchor.lower())
    if anchor_pos == -1:
        return None
    tail = text[anchor_pos + len(anchor) :]
    match = re.search(r"https?://\\S+", tail)
    if match:
        return match.group(0)
    return None


async def download_via_saveasbot(
    url: str,
    target_bot: str,
    download_dir: str,
    timeout_sec: float,
    edit_timeout_sec: float,
) -> tuple[str, str]:
    """Скачивает видео через SaveAsBot и возвращает путь и описание."""
    if not telethon_client.sem or not telethon_client.client:
        raise RuntimeError("Telethon client is not ready")

    async with telethon_client.sem:
        async with telethon_client.client.conversation(target_bot, timeout=timeout_sec) as conv:
            await conv.send_message(str(url))
            logger.info(f"Ссылка отправлена боту: url={url} target_bot={target_bot}")

            video_path = None
            video_caption = ""

            # 1) Wait for the video
            pre_video_description = ""
            awaiting_large_description = False
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
                text = (msg.message or "").strip()
                lower_text = text.lower()
                if awaiting_large_description and text:
                    pre_video_description = text
                    awaiting_large_description = False
                    logger.info("Получено описание после большого видео")
                    if video_path:
                        break
                    continue
                if _UPLOADING_HINT in lower_text:
                    logger.info("Бот сообщил, что видео выгружается")
                    continue
                if _LARGE_VIDEO_HINT in lower_text:
                    download_url = _extract_url_from_buttons(msg, _DOWNLOAD_BUTTON_TEXT)
                    if not download_url:
                        download_url = _extract_url_after_anchor(text, _DOWNLOAD_BUTTON_TEXT)
                    if not download_url:
                        download_url = _extract_url_from_entities(msg)
                    if download_url:
                        logger.info("Найдена ссылка на скачивание большого видео")
                        video_path = _download_video_from_url(
                            download_url,
                            download_dir,
                            timeout_sec,
                        )
                        logger.info(f"Видео скачано по ссылке: video_path={video_path}")
                    else:
                        logger.info("Ссылка на скачивание большого видео не найдена")
                    awaiting_large_description = True
                    continue

            # 2) Нажимаем кнопку "получить текст поста" (она приходит отдельным сообщением после видео)
            desired_button_text = "получить текст поста"
            description = ""

            button_wait_sec = 20
            logger.info(
                f"Ищу кнопку получения текста поста: " f"button_text={desired_button_text} wait_sec={button_wait_sec}"
            )

            button_msg = None
            button_coords = None
            description_candidate = pre_video_description

            if description_candidate:
                description = description_candidate
                logger.info("Использую описание из третьего сообщения, пропускаю поиск кнопки")
            else:
                # Ждем следующее сообщение(я) от SaveAsBot, пока не увидим inline-кнопку
                loop = asyncio.get_running_loop()
                start_ts = loop.time()
                while True:
                    remaining = button_wait_sec - (loop.time() - start_ts)
                    if remaining <= 0:
                        break
                    try:
                        msg = await asyncio.wait_for(conv.get_response(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break
                    logger.info("Получено сообщение от бота (поиск кнопки текста поста)")
                    coords = telethon_client.find_button_coords(msg, desired_button_text)
                    if coords:
                        button_msg = msg
                        button_coords = coords
                        break
                    text = (msg.message or "").strip()
                    if text and not description_candidate:
                        description_candidate = text
                        logger.info("Получено сообщение с текстом без кнопки, сохраняю как кандидат на описание")

                if not button_msg or not button_coords:
                    if description_candidate:
                        description = description_candidate
                        logger.info("Кнопка не найдена за timeout, использую описание из текста")
                        logger.info("Итог: найден текст без кнопки")
                    else:
                        logger.info("Кнопка не найдена за timeout и текста нет, использую caption видео")
                        logger.info("Итог: не найдено ни кнопки, ни текста")
                else:
                    logger.info("Итог: найдена кнопка")
                    # Важно: SaveAsBot после клика обычно НЕ присылает новое сообщение,
                    # а РЕДАКТИРУЕТ то же сообщение с кнопкой. Поэтому ждём edit.
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
                f"used={'post_text' if description else 'caption'}"
            )
            return str(video_path), final_description
