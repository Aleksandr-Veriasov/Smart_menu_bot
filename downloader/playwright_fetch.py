from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Literal, Optional, Any
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PwTimeoutError
from playwright.async_api import async_playwright

from packages.dl_protocol.errors import ErrorCode


Source = Literal['mp4', 'm3u8']

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaywrightResult:
    """Результат извлечения media URL через браузер."""
    media_url: str
    source: Source
    headers: Dict[str, str]  # Рекомендуемые заголовки для последующей загрузки


class FetchError(Exception):
    """
    Ошибка фолбэка Playwright. Содержит код, деталь и признак повторяемости.
    """

    def __init__(
        self, code: ErrorCode, detail: str, *, retryable: bool = False
    ):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


async def get_media(
    url: str,
    *,
    timeout_sec: int = 30,
    proxy: Optional[str] = None,
) -> PlaywrightResult:
    """
    Извлечь прямой media URL (mp4/m3u8) с помощью Playwright.

    :param url: исходный URL ролика (Instagram/TikTok)
    :param timeout_sec: общий таймаут операции (секунды)
    :param proxy: строка прокси (например, 'http://user:pass@host:port'),
    если требуется
    :return: PlaywrightResult(media_url, source, headers)
    :raises FetchError: при ошибках/таймаутах/отсутствии медиа
    """
    ua = _ua_mobile()

    try:
        async with async_playwright() as pw:
            launch_args: Dict[str, Any] = {"headless": True}
            if proxy:
                launch_args['proxy'] = {'server': proxy}
            browser = await pw.chromium.launch(**launch_args)
            context = await browser.new_context(
                user_agent=ua,
                # iPhone 11 Pro Max условно
                viewport={'width': 414, 'height': 896},
                device_scale_factor=3,
                locale='en-US',
                extra_http_headers={
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
            )
            page = await context.new_page()

            # Быстрые перехватчики: ждём подходящий сетевой ответ параллельно
            # с навигацией
            media_future = asyncio.create_task(
                _wait_media_response(page, timeout_sec)
            )

            try:
                await page.goto(
                    url, wait_until='domcontentloaded',
                    timeout=timeout_sec * 1000
                )
            except PwTimeoutError:
                await _safe_close(browser)
                raise FetchError(
                    ErrorCode.TIMEOUT, 'Таймаут загрузки страницы',
                    retryable=True
                )

            # Попробуем дождаться появления <video> и взять src
            media_url = await _extract_from_dom(page, timeout_sec)
            if not media_url:
                # Мягко пробуем кликнуть по странице, чтобы триггерить
                # проигрывание
                try:
                    await page.click('video, body', timeout=1000)
                except Exception:
                    pass
                # Ждём ответа сети (если ещё не пришёл)
                try:
                    media_url = await media_future
                except asyncio.TimeoutError:
                    media_url = None

            # Если обе стратегии не дали результата — считаем,
            # что медиа не найдено
            if not media_url:
                await _safe_close(browser)
                raise FetchError(
                    ErrorCode.NO_MEDIA_FOUND,
                    'Не удалось найти media URL на странице', retryable=False
                )

            # Определяем тип источника
            source: Source = 'm3u8' if '.m3u8' in media_url.lower() else 'mp4'

            # Сформируем рекомендуемые заголовки для дальнейшей загрузки
            headers = await _build_headers(context, page, ua, media_url)

            await _safe_close(browser)
            return PlaywrightResult(
                media_url=media_url, source=source, headers=headers
            )

    except FetchError:
        raise
    except Exception as e:
        # Общая подстраховка
        raise FetchError(ErrorCode.UNKNOWN_ERROR, str(e), retryable=False)


async def _wait_media_response(
    page: Any, timeout_sec: int
) -> Optional[str]:
    """
    Подождать первый сетевой ответ с контентом видео (mp4/m3u8).

    Смотрим на заголовок Content-Type и/или суффикс URL.
    """
    def is_media(resp: Any) -> bool:
        try:
            ct = (resp.headers.get('content-type') or resp.headers.get(
                'Content-Type'
            ) or '').lower()
            url = resp.url.lower()
            if 'video/mp4' in ct:
                return True
            if 'application/vnd.apple.mpegurl' in ct or (
                'application/x-mpegurl' in ct
            ):
                return True
            if url.endswith('.m3u8'):
                return True
            return False
        except Exception:
            return False

    try:
        resp = await page.wait_for_event(
            'response', timeout=timeout_sec * 1000, predicate=is_media
        )
        return str(resp.url) if resp.url else None
    except PwTimeoutError:
        return None


async def _extract_from_dom(page: Any, timeout_sec: int) -> Optional[str]:
    """Попытаться вытащить URL из <video> на странице."""
    try:
        await page.wait_for_selector('video', timeout=timeout_sec * 1000)
    except PwTimeoutError:
        return None

    # Читаем currentSrc/src/source[src]
    try:
        media_url = await page.eval_on_selector(
            'video',
            'el => el.currentSrc || el.src || (el.querySelector("source") '
            '? el.querySelector("source").src : null)',
        )
        # Иногда src='blob:https://...' — это не годится для скачивания →
        # вернём None
        if isinstance(media_url, str) and media_url and (
            not media_url.startswith('blob:')
        ):
            return media_url
    except Exception:
        pass

    return None


async def _build_headers(
    context: Any, page: Any, ua: str, media_url: str
) -> Dict[str, str]:
    """
    Сформировать заголовки для последующей загрузки видео/плейлиста.
    Минимальный набор: User-Agent, Referer.
    """
    headers: Dict[str, str] = {
        'User-Agent': ua,
        'Referer': page.url,
        'Accept': '*/*',
    }

    try:
        # Собираем Cookie для домена медиа (если он совпадает с текущим или
        # связанным доменом)
        mu = urlparse(media_url)
        if mu.hostname:
            cookies = await context.cookies(mu.scheme + '://' + mu.hostname)
        else:
            cookies = []
        if cookies:
            cookie_header = '; '.join(
                f'{c["name"]}={c["value"]}' for c in cookies if (
                    c.get("name") and c.get("value")
                )
            )
            if cookie_header:
                headers['Cookie'] = cookie_header
    except Exception:
        pass

    return headers


async def _safe_close(browser: Any) -> None:
    try:
        await browser.close()
    except Exception:
        pass


def _ua_mobile() -> str:
    """Минимальный мобильный User-Agent, который обычно не ломает IG/TT."""
    return (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
        'Mobile/15E148 Safari/604.1'
    )
