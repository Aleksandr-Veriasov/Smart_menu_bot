from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.enums import (
    BroadcastAudienceType,
    BroadcastCampaignStatus,
    BroadcastMessageStatus,
)

from .base import Base


class BroadcastCampaign(Base):
    """
    Кампания рассылки.

    Управление из кабинета:
    - draft: черновик
    - queued: поставить в очередь (воркер создаст outbox и переведёт в running)
    - running: выполняется
    - paused: пауза (воркер не берёт новые сообщения)
    - completed: закончено (все сообщения sent/failed)
    - cancelled: остановлено (воркер не берёт новые)
    - failed: ошибка конфигурации/фона
    """

    __tablename__ = "broadcast_campaigns"
    __table_args__ = (
        Index("ix_broadcast_campaigns_status", "status"),
        Index("ix_broadcast_campaigns_scheduled_at", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[BroadcastCampaignStatus] = mapped_column(
        SAEnum(BroadcastCampaignStatus, name="broadcast_campaign_status", native_enum=True),
        nullable=False,
        default=BroadcastCampaignStatus.draft,
    )

    # Сегментация (расширяемая).
    audience_type: Mapped[BroadcastAudienceType] = mapped_column(
        SAEnum(BroadcastAudienceType, name="broadcast_audience_type", native_enum=True),
        nullable=False,
        default=BroadcastAudienceType.all_users,
    )
    # JSON-строка (параметры сегмента). Оставляем TEXT, чтобы не привязываться к JSONB.
    audience_params_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Контент.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parse_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="HTML")
    disable_web_page_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # JSON строка reply_markup (InlineKeyboardMarkup и т.п.) как в Bot API.
    reply_markup_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Медиа (минимум для MVP: одно фото).
    photo_file_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Планирование/метрики.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    outbox_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    total_recipients: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    messages: Mapped[list["BroadcastMessage"]] = relationship(
        back_populates="campaign",
        lazy="selectin",
        passive_deletes=True,
        cascade="all, delete-orphan",
    )

    def __str__(self) -> str:
        return f"{self.id}: {self.name}"


class BroadcastMessage(Base):
    """Сообщение outbox для конкретного chat_id."""

    __tablename__ = "broadcast_messages"
    __table_args__ = (
        UniqueConstraint("campaign_id", "chat_id", name="uq_broadcast_campaign_chat"),
        Index("ix_broadcast_messages_campaign_id", "campaign_id"),
        Index("ix_broadcast_messages_status", "status"),
        Index("ix_broadcast_messages_next_retry_at", "next_retry_at"),
        Index("ix_broadcast_messages_locked_until", "locked_until"),
        Index("ix_broadcast_messages_status_next_retry_at", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("broadcast_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    status: Mapped[BroadcastMessageStatus] = mapped_column(
        SAEnum(BroadcastMessageStatus, name="broadcast_message_status", native_enum=True),
        nullable=False,
        default=BroadcastMessageStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped["BroadcastCampaign"] = relationship(back_populates="messages", lazy="selectin")

    def __str__(self) -> str:
        return f"{self.id} ({self.status})"
