import re

from aiogram.filters import BaseFilter
from aiogram.types import Message

_VIDEO_LINK_PATTERN = (
    r"(https?://)?(www\.)?"
    r"("
    r"youtube\.com|youtu\.be|youtube\.com/shorts|tiktok\.com|vm\.tiktok\.com|"
    r"instagram\.com|pinterest\.com|pin\.it|pinterest\.co"
    r")/\S+"
)
_VIDEO_LINK_RE = re.compile(_VIDEO_LINK_PATTERN)


class VideoLinkFilter(BaseFilter):
    """Пропускает только текстовые сообщения, содержащие ссылку на поддерживаемое видео."""

    async def __call__(self, message: Message) -> bool:
        text = message.text or ""
        return bool(text) and bool(_VIDEO_LINK_RE.search(text))
