import logging
import os

import httpx

logger = logging.getLogger(__name__)


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
