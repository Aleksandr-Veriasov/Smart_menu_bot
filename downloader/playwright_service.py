from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Tuple, TYPE_CHECKING
from urllib.parse import parse_qs, unquote

import requests

if TYPE_CHECKING:
    from playwright.sync_api import Page

VIDEO_FOLDER = Path('/app/videos')
VIDEO_FOLDER.mkdir(parents=True, exist_ok=True)

WIDTH_VIDEO = 720
HEIGHT_VIDEO = 1280

logger = logging.getLogger(__name__)


def _platform_from_url(url: str) -> str:
    lower = url.lower()
    if 'instagram.com' in lower:
        return 'instagram'
    if 'tiktok.com' in lower or 'vm.tiktok.com' in lower:
        return 'tiktok'
    if any(domain in lower for domain in ('pinterest.com', 'pin.it', 'pinterest.co')):
        return 'pinterest'
    if 'youtube.com' in lower or 'youtu.be' in lower:
        if '/shorts/' in lower or 'youtube.com/shorts' in lower:
            return 'youtube_shorts'
    return 'unknown'


def _dismiss_instagram_modals(page: 'Page') -> None:
    """Пытаемся закрыть модальные окна согласия/логина."""
    button_variants = [
        'Allow all cookies',
        'Allow all',
        'Allow',
        'Accept all',
        'Разрешить все файлы cookie',
        'Принять все',
    ]
    for text in button_variants:
        try:
            page.get_by_role('button', name=text, exact=False).click(timeout=2000)
            time.sleep(0.5)
            break
        except Exception:
            continue


def _dismiss_tiktok_modals(page: 'Page') -> None:
    selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        'button:has-text("Accept all cookies")',
        'button:has-text("Разрешить все")',
    ]
    for selector in selectors:
        try:
            btn = page.locator(selector)
            if btn.count():
                btn.first.click(timeout=2000)
                time.sleep(0.3)
                break
        except Exception:
            continue


def _dismiss_pinterest_modals(page: 'Page') -> None:
    selectors = [
        'button:has-text("Accept")',
        'button:has-text("Allow all")',
        'button:has-text("Принять")',
        'button:has-text("Разрешить")',
    ]
    for selector in selectors:
        try:
            btn = page.locator(selector)
            if btn.count():
                btn.first.click(timeout=2000)
                time.sleep(0.3)
                break
        except Exception:
            continue


def _dismiss_youtube_modals(page: 'Page') -> None:
    selectors = [
        'button:has-text("I agree")',
        'button:has-text("Yes")',
        'button:has-text("Accept")',
        'button:has-text("Принять")',
    ]
    for selector in selectors:
        try:
            btn = page.locator(selector)
            if btn.count():
                btn.first.click(timeout=2000)
                time.sleep(0.3)
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


def _extract_video_src(page: 'Page', platform: str) -> str:
    video_locator = page.locator('video')
    if video_locator.count():
        src = video_locator.first.evaluate('node => node.currentSrc || node.src || ""')
        if not src:
            src = video_locator.first.get_attribute('src') or ''
        if src and not src.startswith('blob:'):
            return str(src)

    meta_video = page.locator('meta[property="og:video"]')
    if meta_video.count():
        candidate = meta_video.first.get_attribute('content') or ''
        if candidate and not candidate.startswith('blob:'):
            return candidate

    if platform == 'youtube_shorts':
        yt_src = _extract_youtube_stream_url(page)
        if yt_src:
            return yt_src

    if platform == 'pinterest':
        pin_src = _extract_pinterest_video_url(page)
        if pin_src:
            return pin_src

    raise RuntimeError('Playwright не смог найти ссылку на видео на странице.')


def _extract_caption(page: 'Page') -> str:
    selectors = [
        'meta[property="og:description"]',
        'meta[name="description"]',
        'meta[property="og:title"]',
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count():
            value = locator.first.get_attribute('content') or ''
            if value:
                return value
    return ''


def _download_stream(video_url: str, dest_path: Path, referer: str, user_agent: str, cookies: list) -> None:
    headers = {'User-Agent': user_agent, 'Referer': referer}
    cookie_header = '; '.join(
        f'{cookie["name"]}={cookie["value"]}'
        for cookie in cookies
        if cookie.get('name') and cookie.get('value')
    )
    if cookie_header:
        headers['Cookie'] = cookie_header

    with requests.get(video_url, stream=True, headers=headers, timeout=120) as response:
        response.raise_for_status()
        with open(dest_path, 'wb') as dst:
            for chunk in response.iter_content(chunk_size=512 * 1024):
                if chunk:
                    dst.write(chunk)


def download_with_playwright(url: str) -> Tuple[str, str]:
    """
    Скачивает Instagram, TikTok, Pinterest или YouTube Shorts через Playwright.
    Возвращает путь до файла и подпись (description).
    """
    platform = _platform_from_url(url)
    supported = {'instagram', 'tiktok', 'pinterest', 'youtube_shorts'}
    if platform not in supported:
        raise ValueError('Playwright downloader поддерживает только Instagram/TikTok/Pinterest/YouTube Shorts.')

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            'Playwright не установлен. Установите playwright и выполните `playwright install`.'
        ) from exc

    filename = f'{platform}_{int(time.time() * 1000)}.mp4'
    dest_path = VIDEO_FOLDER / filename
    user_agent = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=user_agent,
            viewport={'width': WIDTH_VIDEO, 'height': HEIGHT_VIDEO},
            locale='en-US',
        )
        try:
            page = context.new_page()
            try:
                page.goto(url, wait_until='networkidle', timeout=45_000)
            except PlaywrightTimeoutError:
                page.goto(url, wait_until='domcontentloaded', timeout=45_000)

            if platform == 'instagram':
                _dismiss_instagram_modals(page)
            elif platform == 'tiktok':
                _dismiss_tiktok_modals(page)
            elif platform == 'pinterest':
                _dismiss_pinterest_modals(page)
            elif platform == 'youtube_shorts':
                _dismiss_youtube_modals(page)
            try:
                page.wait_for_selector('video', timeout=30_000)
            except PlaywrightTimeoutError:
                logger.warning('Видео элемент не появился вовремя на %s', page.url)

            video_src = _extract_video_src(page, platform)
            caption = _extract_caption(page)
            cookies = context.cookies()
            referer = page.url
        finally:
            context.close()
            browser.close()

    logger.debug('Playwright (%s) нашёл media URL: %s', platform, video_src)
    _download_stream(video_src, dest_path, referer=referer, user_agent=user_agent, cookies=cookies)
    logger.info('✅ Playwright скачал файл: %s', dest_path)
    return str(dest_path), caption


def _extract_youtube_stream_url(page: 'Page') -> str:
    data_json = page.evaluate(
        '() => {'
        'const resp = window.ytInitialPlayerResponse || window.ytplayer?.config?.args?.player_response;'
        'if (!resp) return null;'
        'if (typeof resp === "string") return resp;'
        'try { return JSON.stringify(resp); } catch (e) { return null; }'
        '}'
    )
    if not data_json:
        return ''
    try:
        data = json.loads(data_json)
    except Exception:
        return ''

    streaming = data.get('streamingData') or {}
    for key in ('formats', 'adaptiveFormats'):
        for fmt in streaming.get(key, []):
            url = fmt.get('url')
            if not url:
                url = _decode_signature_cipher(fmt.get('signatureCipher') or fmt.get('cipher'))
            if url:
                return str(url)
    return ''


def _decode_signature_cipher(cipher: str | None) -> str:
    if not cipher:
        return ''
    params = parse_qs(cipher)
    url = params.get('url', [''])[0]
    if url:
        url = unquote(url)
    sig = params.get('sig', [''])[0] or params.get('signature', [''])[0]
    sp = params.get('sp', ['signature'])[0]
    if url and sig:
        url = f'{url}&{sp}={sig}'
    return url or ''


def _extract_pinterest_video_url(page: 'Page') -> str:
    data_json = page.evaluate(
        '() => window.__PWS_DATA__ ? JSON.stringify(window.__PWS_DATA__) : null'
    )
    if not data_json:
        return ''
    try:
        data = json.loads(data_json)
    except Exception:
        return ''

    def _search(obj: object) -> list[str]:
        results: list[str] = []
        if isinstance(obj, dict):
            if 'video_list' in obj and isinstance(obj['video_list'], dict):
                for variant in obj['video_list'].values():
                    url = (variant or {}).get('url')
                    if url:
                        results.append(url)
            for value in obj.values():
                results.extend(_search(value))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(_search(item))
        return results

    urls = _search(data)
    return urls[0] if urls else ''
