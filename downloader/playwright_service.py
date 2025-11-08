from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Tuple

import requests

VIDEO_FOLDER = Path(os.getenv("VIDEO_FOLDER", "/app/videos"))
VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
try:
    VIDEO_FOLDER.chmod(0o777)
except Exception:
    # Не критично, просто логируем
    logging.getLogger(__name__).warning(
        "Не удалось выставить права 777 на каталог %s", VIDEO_FOLDER
    )
WIDTH_VIDEO = int(os.getenv("PLAYWRIGHT_VIEWPORT_WIDTH", "720"))
HEIGHT_VIDEO = int(os.getenv("PLAYWRIGHT_VIEWPORT_HEIGHT", "1280"))

logger = logging.getLogger(__name__)


def _dismiss_instagram_modals(page) -> None:
    """Пытаемся закрыть модальные окна согласия/логина."""
    button_variants = [
        "Allow all cookies",
        "Allow all",
        "Allow",
        "Accept all",
        "Разрешить все файлы cookie",
        "Принять все",
    ]
    for text in button_variants:
        try:
            page.get_by_role("button", name=text, exact=False).click(timeout=2000)
            time.sleep(0.5)
            break
        except Exception:
            continue

    close_selectors = [
        '[aria-label="Close"]',
        '[aria-label="Закрыть"]',
        'div[role="dialog"] button:has-text("Not Now")',
    ]
    for selector in close_selectors:
        try:
            dialog = page.locator(selector)
            if dialog.count():
                dialog.first.click(timeout=2000)
                time.sleep(0.3)
                break
        except Exception:
            continue


def _extract_instagram_video_src(page) -> str:
    video_locator = page.locator("video")
    if video_locator.count():
        src = video_locator.first.evaluate("node => node.currentSrc || node.src || ''")
        if not src:
            src = video_locator.first.get_attribute("src") or ""
        if src:
            return src

    meta_video = page.locator('meta[property="og:video"]')
    if meta_video.count():
        candidate = meta_video.first.get_attribute("content") or ""
        if candidate:
            return candidate

    raise RuntimeError("Playwright не нашёл ссылку на видео на странице Instagram.")


def _instagram_caption_from_page(page) -> str:
    selectors = [
        'meta[property="og:description"]',
        'meta[name="description"]',
        'meta[property="og:title"]',
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count():
            value = locator.first.get_attribute("content") or ""
            if value:
                return value
    return ""


def _download_stream(video_url: str, dest_path: Path, referer: str, user_agent: str, cookies: list) -> None:
    headers = {"User-Agent": user_agent, "Referer": referer}
    cookie_header = "; ".join(
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if cookie.get("name") and cookie.get("value")
    )
    if cookie_header:
        headers["Cookie"] = cookie_header

    with requests.get(video_url, stream=True, headers=headers, timeout=60) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as dst:
            for chunk in response.iter_content(chunk_size=512 * 1024):
                if chunk:
                    dst.write(chunk)


def download_instagram_with_playwright(url: str) -> Tuple[str, str]:
    """
    Скачивает Instagram-видео через Playwright и сохраняет файл на диск.
    Возвращает путь до файла и подпись (description).
    """
    if "instagram.com" not in url.lower():
        raise ValueError("Playwright downloader поддерживает только Instagram.")

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright не установлен. Установите playwright и выполните `playwright install`."
        ) from exc

    VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)
    filename = f'instagram_{int(time.time() * 1000)}.mp4'
    dest_path = VIDEO_FOLDER / filename
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=user_agent,
            viewport={"width": WIDTH_VIDEO, "height": HEIGHT_VIDEO},
            locale="en-US",
        )
        try:
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
            except PlaywrightTimeoutError:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)

            _dismiss_instagram_modals(page)
            video_src = _extract_instagram_video_src(page)
            caption = _instagram_caption_from_page(page)
            cookies = context.cookies()
        finally:
            context.close()
            browser.close()

    logger.debug("Playwright нашёл media URL: %s", video_src)
    _download_stream(video_src, dest_path, referer=url, user_agent=user_agent, cookies=cookies)
    try:
        dest_path.chmod(0o666)
    except Exception:
        logger.warning("Не удалось выставить права 666 на файл %s", dest_path)
    logger.info("✅ Playwright скачал файл: %s", dest_path)
    return str(dest_path), caption
