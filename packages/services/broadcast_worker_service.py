from datetime import UTC, datetime, timedelta
from typing import Any

from packages.db.models.broadcast import BroadcastCampaign
from packages.db.repository import BroadcastRepository
from packages.integrations.telegram_api import backoff_seconds, send_campaign_message
from packages.services.base import BaseService


class BroadcastWorkerService(BaseService):
    """Сервис для воркера рассылок: оркестрирует отправку через репозиторий и Bot API."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._repo = BroadcastRepository

    async def init_due_campaigns(self) -> None:
        """Перевести готовые queued-кампании в running и построить outbox."""
        async with self.db.session() as session:
            await self._repo(session).init_due_campaigns()

    async def list_active_campaign_ids(self) -> list[int]:
        """Вернуть id всех running-кампаний."""
        async with self.db.session() as session:
            return await self._repo(session).list_active_campaign_ids()

    async def claim_messages(self, campaign_id: int, *, batch_size: int) -> list[tuple[int, int, int]]:
        """Атомарно забрать пачку сообщений кампании; возвращает (message_id, chat_id, attempt)."""
        async with self.db.session() as session:
            return await self._repo(session).claim_messages_for_campaign(campaign_id=campaign_id, batch_size=batch_size)

    async def send_to_chat(self, campaign_id: int, *, chat_id: int) -> dict[str, Any]:
        """Отправить сообщение кампании в чат через Telegram Bot API."""
        from packages.common_settings.settings import settings

        async with self.db.session() as session:
            campaign: BroadcastCampaign | None = await self._repo(session).get_campaign_or_none(campaign_id)
        if campaign is None:
            return {"ok": False, "description": "Campaign not found"}
        return await send_campaign_message(
            campaign,
            chat_id=chat_id,
            bot_token=settings.telegram.bot_token.get_secret_value().strip(),
            timeout=settings.broadcast.request_timeout_sec,
        )

    async def mark_message_sent(self, *, campaign_id: int, message_id: int) -> None:
        """Пометить сообщение отправленным и увеличить sent_count кампании."""
        async with self.db.session() as session:
            await self._repo(session).mark_message_sent(campaign_id=campaign_id, message_id=message_id)

    async def mark_message_failed(self, *, campaign_id: int, message_id: int, error: str) -> None:
        """Пометить сообщение failed и увеличить failed_count кампании."""
        async with self.db.session() as session:
            await self._repo(session).mark_message_failed(campaign_id=campaign_id, message_id=message_id, error=error)

    async def schedule_retry(self, *, message_id: int, error: str, retry_after_sec: float | None, attempt: int) -> None:
        """Перевести сообщение в retry; вычисляет next_retry_at через backoff или retry_after."""
        delay = float(retry_after_sec or backoff_seconds(attempt))
        next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)
        async with self.db.session() as session:
            await self._repo(session).schedule_retry(message_id=message_id, error=error, next_retry_at=next_retry_at)

    async def complete_finished_campaigns(self) -> None:
        """Перевести в completed кампании, у которых не осталось необработанных сообщений."""
        async with self.db.session() as session:
            await self._repo(session).complete_finished_campaigns()
