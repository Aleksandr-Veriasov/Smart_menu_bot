import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PipelineJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class PipelineJob(Base):
    """
    Durable-очередь задач видео-пайплайна (transactional outbox).

    Запись создаётся ботом атомарно в той же транзакции, что и ответ пользователю.
    media_worker забирает задачи через SELECT FOR UPDATE SKIP LOCKED и обрабатывает
    их изолированно. Идемпотентность гарантируется уникальным (chat_id, message_id).
    """

    __tablename__ = "pipeline_jobs"
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_pipeline_jobs_chat_message"),
        Index("ix_pipeline_jobs_chat_message", "chat_id", "message_id", unique=True),
        Index("ix_pipeline_jobs_status_retry", "status", "next_retry_at"),
        Index("ix_pipeline_jobs_locked_until", "locked_until"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)

    status: Mapped[PipelineJobStatus] = mapped_column(
        SAEnum(PipelineJobStatus, name="pipeline_job_status", native_enum=True),
        nullable=False,
        default=PipelineJobStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __str__(self) -> str:
        return f"PipelineJob(id={self.id}, chat_id={self.chat_id}, message_id={self.message_id}, status={self.status})"
