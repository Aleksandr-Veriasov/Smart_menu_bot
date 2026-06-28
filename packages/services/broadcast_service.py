from datetime import datetime, timezone

from packages.db.repository import BroadcastRepository
from packages.schemas.broadcast import (
    BroadcastCampaignCreate,
    BroadcastCampaignRead,
    BroadcastCampaignUpdate,
    BroadcastMessageRead,
)
from packages.services.base import BaseService


class BroadcastService(BaseService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.repo = BroadcastRepository

    async def list_campaigns(self, limit: int = 50) -> list[BroadcastCampaignRead]:
        """Вернуть список кампаний, от новых к старым."""
        async with self.db.session() as session:
            items = await self.repo(session).list_campaigns(limit=limit)
            return [BroadcastCampaignRead.model_validate(x) for x in items]

    async def create_campaign(self, payload: BroadcastCampaignCreate) -> BroadcastCampaignRead:
        """Создать новую рассылочную кампанию."""
        async with self.db.session() as session:
            campaign = await self.repo(session).create_campaign(
                name=payload.name,
                status=payload.status,
                audience_type=payload.audience_type,
                audience_params_json=payload.audience_params_json,
                text=payload.text,
                parse_mode=payload.parse_mode,
                disable_web_page_preview=payload.disable_web_page_preview,
                reply_markup_json=payload.reply_markup_json,
                photo_file_id=payload.photo_file_id,
                photo_url=payload.photo_url,
                scheduled_at=payload.scheduled_at,
            )
            return BroadcastCampaignRead.model_validate(campaign)

    async def update_campaign(self, campaign_id: int, payload: BroadcastCampaignUpdate) -> BroadcastCampaignRead:
        """Обновить черновик кампании. Raises LookupError / ValueError."""
        async with self.db.session() as session:
            campaign = await self.repo(session).update_campaign(
                campaign_id=campaign_id,
                changes=payload.model_dump(exclude_unset=True, exclude_none=True),
            )
            return BroadcastCampaignRead.model_validate(campaign)

    async def queue_campaign(self, campaign_id: int) -> BroadcastCampaignRead:
        """Поставить кампанию в очередь. Raises LookupError / ValueError."""
        async with self.db.session() as session:
            campaign = await self.repo(session).queue_campaign(campaign_id=campaign_id)
            return BroadcastCampaignRead.model_validate(campaign)

    async def pause_campaign(self, campaign_id: int) -> BroadcastCampaignRead:
        """Приостановить кампанию. Raises LookupError / ValueError."""
        async with self.db.session() as session:
            campaign = await self.repo(session).pause_campaign(campaign_id=campaign_id)
            return BroadcastCampaignRead.model_validate(campaign)

    async def resume_campaign(self, campaign_id: int) -> BroadcastCampaignRead:
        """Возобновить приостановленную кампанию. Raises LookupError / ValueError."""
        async with self.db.session() as session:
            campaign = await self.repo(session).resume_campaign(
                campaign_id=campaign_id,
                now_utc=datetime.now(timezone.utc),
            )
            return BroadcastCampaignRead.model_validate(campaign)

    async def cancel_campaign(self, campaign_id: int) -> BroadcastCampaignRead:
        """Отменить кампанию. Raises LookupError."""
        async with self.db.session() as session:
            campaign = await self.repo(session).cancel_campaign(
                campaign_id=campaign_id,
                now_utc=datetime.now(timezone.utc),
            )
            return BroadcastCampaignRead.model_validate(campaign)

    async def list_messages(self, campaign_id: int, limit: int = 200) -> list[BroadcastMessageRead]:
        """Вернуть сообщения кампании, от новых к старым."""
        async with self.db.session() as session:
            items = await self.repo(session).list_messages(campaign_id=campaign_id, limit=limit)
            return [BroadcastMessageRead.model_validate(x) for x in items]
