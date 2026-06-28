import re

from aiogram.filters import BaseFilter
from aiogram.types import Message

_VIDEO_LINK_PATTERN = (
    r"(https?://)?(www\.)?"
    r"("
    r"tiktok\.com|vm\.tiktok\.com|"
    r"instagram\.com|pinterest\.com|pin\.it|pinterest\.co"
    r")/\S+"
)
_VIDEO_LINK_RE = re.compile(_VIDEO_LINK_PATTERN)

_ANY_URL_RE = re.compile(r"https?://\S+")


class VideoLinkFilter(BaseFilter):
    """Пропускает только текстовые сообщения, содержащие ссылку на поддерживаемое видео."""

    async def __call__(self, message: Message) -> bool:
        text = message.text or ""
        return bool(text) and bool(_VIDEO_LINK_RE.search(text))


class UnsupportedLinkFilter(BaseFilter):
    """Пропускает сообщения с любой http-ссылкой, которая НЕ является поддерживаемым видео."""

    async def __call__(self, message: Message) -> bool:
        text = message.text or ""
        if not text:
            return False
        return bool(_ANY_URL_RE.search(text)) and not bool(_VIDEO_LINK_RE.search(text))
