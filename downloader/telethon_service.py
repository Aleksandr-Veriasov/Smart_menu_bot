import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TELETHON_DELAY_ON_CONCURRENCY_SEC = 6.0
_telethon_lock = asyncio.Lock()
_telethon_in_flight = 0


async def delay_if_telethon_busy() -> None:
    """Если уже есть активный Telethon-запрос, задерживает текущий."""
    global _telethon_in_flight
    delay = 0.0
    async with _telethon_lock:
        if _telethon_in_flight > 0:
            delay = _TELETHON_DELAY_ON_CONCURRENCY_SEC
        _telethon_in_flight += 1
    if delay:
        await asyncio.sleep(delay)


async def release_telethon_slot() -> None:
    """Уменьшает счетчик активных Telethon-запросов."""
    global _telethon_in_flight
    async with _telethon_lock:
        _telethon_in_flight = max(0, _telethon_in_flight - 1)


def telethon_base_url() -> str | None:
    base_url = os.getenv("TELETHON_BASE_URL")
    if not base_url:
        return None
    return base_url.rstrip("/")


async def download_video_via_telethon(url: str) -> tuple[str, str]:
    """Fallback downloader via Telethon worker.

    Expected Telethon worker contract:
      POST {TELETHON_BASE_URL}/download
      body: {"url": "https://..."}
      response: {"file_path": "...", "description": "..."}

    Raises RuntimeError if TELETHON_BASE_URL is not configured or if the worker returns an error.
    """
    base_url = telethon_base_url()
    if not base_url:
        raise RuntimeError("TELETHON_BASE_URL is not configured")

    endpoint = f"{base_url}/download"
    timeout_sec = float(os.getenv("TELETHON_TIMEOUT_SEC", "180"))

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(endpoint, json={"url": url})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        # propagate worker errors with context
        raise RuntimeError(f"Telethon worker error: {exc.response.status_code} {exc.response.text}") from exc
    except Exception as exc:
        raise RuntimeError(f"Telethon worker request failed: {exc}") from exc

    file_path = data.get("file_path")
    description = data.get("description") or ""
    if not file_path:
        raise RuntimeError(f"Telethon worker returned invalid response: {data}")

    return str(file_path), str(description)
