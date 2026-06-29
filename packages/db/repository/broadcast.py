from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.db.models import BroadcastCampaign, BroadcastMessage, User
from packages.enums import (
    BroadcastAudienceType,
    BroadcastCampaignStatus,
    BroadcastMessageStatus,
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

    # ── Admin panel methods ───────────────────────────────────────────────────

    async def list_campaigns_page(self, *, offset: int, limit: int) -> tuple[list[BroadcastCampaign], int]:
        """Вернуть страницу кампаний и их общее количество."""
        total = (await self.session.execute(select(func.count(BroadcastCampaign.id)))).scalar_one()
        res = await self.session.execute(
            select(BroadcastCampaign).order_by(desc(BroadcastCampaign.id)).offset(offset).limit(limit)
        )
        return list(res.scalars().all()), int(total)

    async def admin_update_campaign(
        self,
        *,
        campaign_id: int,
        name: str,
        status: BroadcastCampaignStatus,
        audience_type: BroadcastAudienceType,
        text: str,
        parse_mode: str,
        scheduled_at: datetime | None,
        photo_file_id: str | None,
        photo_url: str | None,
        reply_markup_json: str | None,
        disable_web_page_preview: bool,
    ) -> BroadcastCampaign:
        """Обновить поля кампании без ограничений (для admin-панели)."""
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign is None:
            raise LookupError(f"Кампания #{campaign_id} не найдена")
        campaign.name = name
        campaign.status = status
        campaign.audience_type = audience_type
        campaign.text = text
        campaign.parse_mode = parse_mode
        campaign.scheduled_at = scheduled_at
        campaign.photo_file_id = photo_file_id
        campaign.photo_url = photo_url
        campaign.reply_markup_json = reply_markup_json
        campaign.disable_web_page_preview = disable_web_page_preview
        return await self.save(campaign)

    async def delete_campaign(self, *, campaign_id: int) -> None:
        """Удалить кампанию по id."""
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign:
            await self.session.delete(campaign)

    async def list_messages_page(
        self, *, campaign_id: int, offset: int, limit: int, status_filter: str
    ) -> tuple[list[BroadcastMessage], int]:
        """Вернуть страницу сообщений кампании и их общее количество."""
        base = select(BroadcastMessage).where(BroadcastMessage.campaign_id == int(campaign_id))
        if status_filter:
            base = base.where(BroadcastMessage.status == status_filter)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        res = await self.session.execute(base.order_by(desc(BroadcastMessage.id)).offset(offset).limit(limit))
        return list(res.scalars().all()), int(total)

    # ── Worker methods ────────────────────────────────────────────────────────

    async def init_due_campaigns(self, *, limit: int = 20) -> None:
        """Перевести готовые queued-кампании в running и построить outbox."""
        now = datetime.now(UTC)
        res = await self.session.execute(
            select(BroadcastCampaign)
            .where(
                BroadcastCampaign.status == BroadcastCampaignStatus.queued,
                (BroadcastCampaign.scheduled_at.is_(None)) | (BroadcastCampaign.scheduled_at <= now),
            )
            .order_by(BroadcastCampaign.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True),
        )
        due = list(res.scalars().all())
        for c in due:
            if c.audience_type != BroadcastAudienceType.all_users:
                c.status = BroadcastCampaignStatus.failed
                c.last_error = f"Неподдерживаемый audience_type: {c.audience_type}"
                c.finished_at = now
                continue
            if c.outbox_created_at is None:
                await self.build_outbox_all_users(campaign_id=int(c.id))
                c.outbox_created_at = now
            cnt = await self.session.execute(
                select(func.count(BroadcastMessage.id)).where(BroadcastMessage.campaign_id == int(c.id))
            )
            c.total_recipients = int(cnt.scalar() or 0)
            c.status = BroadcastCampaignStatus.running
            if c.started_at is None:
                c.started_at = now

    async def list_active_campaign_ids(self, *, limit: int = 50) -> list[int]:
        """Вернуть id активных (running) кампаний."""
        res = await self.session.execute(
            select(BroadcastCampaign.id)
            .where(BroadcastCampaign.status == BroadcastCampaignStatus.running)
            .order_by(BroadcastCampaign.id.asc())
            .limit(limit)
        )
        return [int(x) for x in res.scalars().all()]

    async def claim_messages_for_campaign(self, *, campaign_id: int, batch_size: int) -> list[tuple[int, int, int]]:
        """Атомарно забрать пачку сообщений в обработку.

        Сначала проверяет, что кампания ещё running — возвращает [] если нет.
        Возвращает список (message_id, chat_id, attempts_after_claim).
        """
        campaign = await self.get_campaign_or_none(campaign_id)
        if campaign is None or campaign.status != BroadcastCampaignStatus.running:
            return []

        now = datetime.now(UTC)
        lock_until = now + timedelta(seconds=120)
        res = await self.session.execute(
            select(BroadcastMessage)
            .where(
                BroadcastMessage.campaign_id == int(campaign_id),
                BroadcastMessage.status.in_(
                    [
                        BroadcastMessageStatus.pending,
                        BroadcastMessageStatus.retry,
                        BroadcastMessageStatus.sending,
                    ]
                ),
                (BroadcastMessage.locked_until.is_(None)) | (BroadcastMessage.locked_until <= now),
                (BroadcastMessage.next_retry_at.is_(None)) | (BroadcastMessage.next_retry_at <= now),
            )
            .order_by(BroadcastMessage.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True),
        )
        rows = list(res.scalars().all())
        claimed: list[tuple[int, int, int]] = []
        for m in rows:
            m.status = BroadcastMessageStatus.sending
            m.attempts = int(m.attempts or 0) + 1
            m.next_retry_at = None
            m.locked_until = lock_until
            m.last_error = None
            claimed.append((int(m.id), int(m.chat_id), int(m.attempts)))
        return claimed

    async def mark_message_sent(self, *, campaign_id: int, message_id: int) -> None:
        """Пометить сообщение отправленным и увеличить sent_count кампании."""
        now = datetime.now(UTC)
        await self.session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == int(message_id))
            .values(status=BroadcastMessageStatus.sent, sent_at=now, next_retry_at=None, locked_until=None)
        )
        await self.session.execute(
            update(BroadcastCampaign)
            .where(BroadcastCampaign.id == int(campaign_id))
            .values(sent_count=BroadcastCampaign.sent_count + 1)
        )

    async def mark_message_failed(self, *, campaign_id: int, message_id: int, error: str) -> None:
        """Пометить сообщение failed и увеличить failed_count кампании."""
        await self.session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == int(message_id))
            .values(
                status=BroadcastMessageStatus.failed,
                last_error=error[:2000],
                next_retry_at=None,
                locked_until=None,
            )
        )
        await self.session.execute(
            update(BroadcastCampaign)
            .where(BroadcastCampaign.id == int(campaign_id))
            .values(failed_count=BroadcastCampaign.failed_count + 1)
        )

    async def schedule_retry(self, *, message_id: int, error: str, next_retry_at: datetime) -> None:
        """Перевести сообщение в retry с назначенным временем следующей попытки."""
        await self.session.execute(
            update(BroadcastMessage)
            .where(BroadcastMessage.id == int(message_id))
            .values(
                status=BroadcastMessageStatus.retry,
                next_retry_at=next_retry_at,
                locked_until=None,
                last_error=error[:2000],
            )
        )

    async def complete_finished_campaigns(self, *, limit: int = 50) -> None:
        """Закрыть running-кампании, у которых не осталось необработанных сообщений."""
        now = datetime.now(UTC)
        res = await self.session.execute(
            select(BroadcastCampaign.id)
            .where(BroadcastCampaign.status == BroadcastCampaignStatus.running)
            .order_by(BroadcastCampaign.id.asc())
            .limit(limit)
        )
        ids = [int(x) for x in res.scalars().all()]
        for cid in ids:
            pending = await self.session.execute(
                select(func.count(BroadcastMessage.id)).where(
                    BroadcastMessage.campaign_id == cid,
                    BroadcastMessage.status.in_(
                        [
                            BroadcastMessageStatus.pending,
                            BroadcastMessageStatus.retry,
                            BroadcastMessageStatus.sending,
                        ]
                    ),
                )
            )
            if int(pending.scalar() or 0) == 0:
                await self.session.execute(
                    update(BroadcastCampaign)
                    .where(
                        BroadcastCampaign.id == cid,
                        BroadcastCampaign.status == BroadcastCampaignStatus.running,
                    )
                    .values(status=BroadcastCampaignStatus.completed, finished_at=now)
                )
