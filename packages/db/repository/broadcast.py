from typing import Any

import sqlalchemy as sa
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.db.models import (
    BroadcastCampaign,
    BroadcastCampaignStatus,
    BroadcastMessage,
    BroadcastMessageStatus,
    User,
)

from .base import SessionMixin


class BroadcastRepository(SessionMixin):
    """Репозиторий для управления рассылочными кампаниями и их сообщениями."""

    async def count(self) -> int:
        """Вернуть общее количество кампаний."""
        result = await self.session.execute(select(func.count(BroadcastCampaign.id)))
        return result.scalar_one_or_none() or 0

    async def count_running(self) -> int:
        """Вернуть количество активных (running) кампаний."""
        result = await self.session.execute(
            select(func.count(BroadcastCampaign.id)).where(BroadcastCampaign.status == BroadcastCampaignStatus.running)
        )
        return result.scalar_one_or_none() or 0

    async def build_outbox_all_users(self, *, campaign_id: int) -> None:
        """Построить outbox для кампании по аудитории all_users. Дубликаты игнорируются."""
        insert_stmt = pg_insert(BroadcastMessage).from_select(
            ["campaign_id", "chat_id", "status", "attempts"],
            select(
                sa.literal(int(campaign_id)),
                User.id,
                sa.literal(BroadcastMessageStatus.pending),
                sa.literal(0),
            ),
        )
        stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=[BroadcastMessage.campaign_id, BroadcastMessage.chat_id]
        )
        await self.session.execute(stmt)

    async def list_campaigns(self, *, limit: int) -> list[BroadcastCampaign]:
        """Вернуть последние кампании, от новых к старым."""
        stmt = select(BroadcastCampaign).order_by(desc(BroadcastCampaign.id)).limit(max(1, min(200, int(limit))))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def create_campaign(
        self,
        *,
        name: str,
        status,
        audience_type,
        audience_params_json: str | None,
        text: str,
        parse_mode: str,
        disable_web_page_preview: bool,
        reply_markup_json: str | None,
        photo_file_id: str | None,
        photo_url: str | None,
        scheduled_at,
    ) -> BroadcastCampaign:
        """Создать новую рассылочную кампанию."""
        campaign = BroadcastCampaign(
            name=name,
            status=status,
            audience_type=audience_type,
            audience_params_json=audience_params_json,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup_json=reply_markup_json,
            photo_file_id=photo_file_id,
            photo_url=photo_url,
            scheduled_at=scheduled_at,
        )
        self.session.add(campaign)
        return await self.save(campaign)

    async def get_campaign_or_none(self, campaign_id: int) -> BroadcastCampaign | None:
        """Найти кампанию по id."""
        res = await self.session.execute(select(BroadcastCampaign).where(BroadcastCampaign.id == int(campaign_id)))
        return res.scalar_one_or_none()

    async def update_campaign(
        self,
        *,
        campaign_id: int,
        changes: dict[str, Any],
    ) -> BroadcastCampaign:
        """Обновить черновик кампании. Запрещено после начала доставки или завершения."""
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if int(campaign.sent_count or 0) > 0 or int(campaign.failed_count or 0) > 0:
            raise ValueError("Campaign already has deliveries; create a new campaign instead")
        if campaign.status == BroadcastCampaignStatus.completed:
            raise ValueError("Completed campaign is immutable; create a new campaign instead")
        for field, value in changes.items():
            setattr(campaign, field, value)
        return await self.save(campaign)

    async def queue_campaign(self, *, campaign_id: int) -> BroadcastCampaign:
        """Перевести кампанию в статус queued из draft/paused/failed."""
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status not in (
            BroadcastCampaignStatus.draft,
            BroadcastCampaignStatus.paused,
            BroadcastCampaignStatus.failed,
        ):
            raise ValueError(f"Cannot queue from status={campaign.status.value}")
        campaign.status = BroadcastCampaignStatus.queued
        campaign.last_error = None
        campaign.finished_at = None
        return await self.save(campaign)

    async def pause_campaign(self, *, campaign_id: int) -> BroadcastCampaign:
        """Поставить кампанию на паузу. Только из статуса running."""
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status != BroadcastCampaignStatus.running:
            raise ValueError(f"Cannot pause from status={campaign.status.value}")
        campaign.status = BroadcastCampaignStatus.paused
        return await self.save(campaign)

    async def resume_campaign(self, *, campaign_id: int, now_utc) -> BroadcastCampaign:
        """Возобновить приостановленную кампанию."""
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status != BroadcastCampaignStatus.paused:
            raise ValueError(f"Cannot resume from status={campaign.status.value}")
        campaign.status = BroadcastCampaignStatus.running
        if campaign.started_at is None:
            campaign.started_at = now_utc
        return await self.save(campaign)

    async def cancel_campaign(self, *, campaign_id: int, now_utc) -> BroadcastCampaign:
        """Отменить кампанию. Идемпотентно для уже завершённых/отменённых."""
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status in (BroadcastCampaignStatus.completed, BroadcastCampaignStatus.cancelled):
            return campaign
        campaign.status = BroadcastCampaignStatus.cancelled
        campaign.finished_at = now_utc
        return await self.save(campaign)

    async def list_messages(self, *, campaign_id: int, limit: int) -> list[BroadcastMessage]:
        """Вернуть сообщения кампании, от новых к старым."""
        stmt = (
            select(BroadcastMessage)
            .where(BroadcastMessage.campaign_id == int(campaign_id))
            .order_by(desc(BroadcastMessage.id))
            .limit(max(1, min(500, int(limit))))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
