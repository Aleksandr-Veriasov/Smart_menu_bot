from datetime import UTC, datetime

from packages.db.models.broadcast import BroadcastCampaign, BroadcastMessage
from packages.db.repository import BroadcastRepository
from packages.enums import (
    BroadcastAudienceType,
    BroadcastCampaignStatus,
    BroadcastMessageStatus,
)
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
                now_utc=datetime.now(UTC),
            )
            return BroadcastCampaignRead.model_validate(campaign)

    async def cancel_campaign(self, campaign_id: int) -> BroadcastCampaignRead:
        """Отменить кампанию. Raises LookupError."""
        async with self.db.session() as session:
            campaign = await self.repo(session).cancel_campaign(
                campaign_id=campaign_id,
                now_utc=datetime.now(UTC),
            )
            return BroadcastCampaignRead.model_validate(campaign)

    async def list_messages(self, campaign_id: int, limit: int = 200) -> list[BroadcastMessageRead]:
        """Вернуть сообщения кампании, от новых к старым."""
        async with self.db.session() as session:
            items = await self.repo(session).list_messages(campaign_id=campaign_id, limit=limit)
            return [BroadcastMessageRead.model_validate(x) for x in items]

    # ── Admin panel ───────────────────────────────────────────────────────────

    async def list_campaigns_page(self, page: int, page_size: int) -> tuple[list[BroadcastCampaign], int]:
        """Вернуть страницу кампаний и общее количество для admin-панели."""
        offset = (page - 1) * page_size
        async with self.db.session() as session:
            return await self.repo(session).list_campaigns_page(offset=offset, limit=page_size)

    async def get_campaign_or_raise(self, campaign_id: int) -> BroadcastCampaign:
        """Вернуть кампанию или бросить LookupError."""
        async with self.db.session() as session:
            campaign = await self.repo(session).get_campaign_or_none(campaign_id)
        if campaign is None:
            raise LookupError(f"Кампания #{campaign_id} не найдена")
        return campaign

    async def admin_update_campaign(
        self,
        campaign_id: int,
        *,
        name: str,
        status: str,
        audience_type: str,
        text: str,
        parse_mode: str,
        scheduled_at: datetime | None,
        photo_file_id: str | None = None,
        photo_url: str | None = None,
        reply_markup_json: str | None = None,
        disable_web_page_preview: bool = True,
    ) -> BroadcastCampaign:
        """Обновить кампанию из admin-формы без ограничений на статус."""
        async with self.db.session() as session:
            return await self.repo(session).admin_update_campaign(
                campaign_id=campaign_id,
                name=name,
                status=BroadcastCampaignStatus(status),
                audience_type=BroadcastAudienceType(audience_type),
                text=text,
                parse_mode=parse_mode,
                scheduled_at=scheduled_at,
                photo_file_id=photo_file_id,
                photo_url=photo_url,
                reply_markup_json=reply_markup_json,
                disable_web_page_preview=disable_web_page_preview,
            )

    async def delete_campaign(self, campaign_id: int) -> None:
        """Удалить кампанию."""
        async with self.db.session() as session:
            await self.repo(session).delete_campaign(campaign_id=campaign_id)

    async def list_messages_page(
        self, campaign_id: int, page: int, page_size: int, status_filter: str
    ) -> tuple[BroadcastCampaign, list[BroadcastMessage], int]:
        """Вернуть кампанию, страницу сообщений и общее количество для admin-панели."""
        offset = (page - 1) * page_size
        async with self.db.session() as session:
            campaign = await self.repo(session).get_campaign_or_none(campaign_id)
            if campaign is None:
                raise LookupError(f"Кампания #{campaign_id} не найдена")
            messages, total = await self.repo(session).list_messages_page(
                campaign_id=campaign_id, offset=offset, limit=page_size, status_filter=status_filter
            )
        return campaign, messages, total

    @staticmethod
    def message_statuses() -> list[str]:
        """Вернуть список всех возможных статусов сообщения."""
        return [s.value for s in BroadcastMessageStatus]
