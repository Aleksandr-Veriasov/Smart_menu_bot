import re

from aiogram.enums import MessageEntityType
from aiogram.types import Message

_URL_RE = re.compile(r"(?P<url>https?://(?:www\.)?[^\s<>()\[\]]+)", re.IGNORECASE)


def extract_first_url(message: Message) -> str | None:
    """Возвращает первую ссылку из текста/подписи сообщения, если она есть."""
    for entities, source_text in (
        (message.entities, message.text),
        (message.caption_entities, message.caption),
    ):
        if not entities or not source_text:
            continue
        for entity in entities:
            if entity.type == MessageEntityType.TEXT_LINK and entity.url:
                return entity.url
            if entity.type == MessageEntityType.URL:
                return entity.extract_from(source_text)

    source_text = message.text or message.caption or ""
    match = _URL_RE.search(source_text)
    return match.group("url").rstrip(".,);:!?]»”") if match else None
