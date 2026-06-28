from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from packages.db.models.pipeline import PipelineJob, PipelineJobStatus
from packages.db.repository.base import BaseRepository

_LOCK_TTL_SECONDS = 300
_RETRY_BASE_SECONDS = 60
_RETRY_MAX_SECONDS = 3600
_MAX_ATTEMPTS = 5


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _backoff(attempts: int) -> timedelta:
    seconds = min(_RETRY_BASE_SECONDS * (2 ** (attempts - 1)), _RETRY_MAX_SECONDS)
    return timedelta(seconds=seconds)


class PipelineJobRepository(BaseRepository[PipelineJob]):
    model = PipelineJob

    async def enqueue(
        self,
        *,
        chat_id: int,
        message_id: int,
        user_id: int,
        url: str,
    ) -> PipelineJob:
        """Добавить задачу в очередь (идемпотентно: при дубле возвращает существующую)."""
        existing = await self.session.scalar(
            select(self.model).where(
                self.model.chat_id == chat_id,
                self.model.message_id == message_id,
            )
        )
        if existing is not None:
            return existing

        job = self.model(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            url=url,
            status=PipelineJobStatus.pending,
        )
        self.session.add(job)
        return await self.save(job)

    async def claim(self, *, batch_size: int = 1) -> list[PipelineJob]:
        """Атомарно забрать задачи для обработки (FOR UPDATE SKIP LOCKED)."""
        now = _utcnow()
        result = await self.session.execute(
            select(self.model)
            .where(
                self.model.status.in_([PipelineJobStatus.pending]),
                (self.model.locked_until.is_(None)) | (self.model.locked_until <= now),
                (self.model.next_retry_at.is_(None)) | (self.model.next_retry_at <= now),
            )
            .order_by(self.model.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True),
        )
        jobs = list(result.scalars().all())
        if not jobs:
            return []

        lock_until = now + timedelta(seconds=_LOCK_TTL_SECONDS)
        for job in jobs:
            job.status = PipelineJobStatus.running
            job.attempts = (job.attempts or 0) + 1
            job.locked_until = lock_until
            job.next_retry_at = None
            job.last_error = None

        await self.session.flush()
        return jobs

    async def ack(self, job_id: int) -> None:
        """Пометить задачу как выполненную."""
        await self.session.execute(
            update(self.model)
            .where(self.model.id == job_id)
            .values(
                status=PipelineJobStatus.done,
                locked_until=None,
                next_retry_at=None,
                last_error=None,
            )
        )

    async def nack(self, job_id: int, *, error: str) -> None:
        """Вернуть задачу в очередь (retry) или пометить failed (исчерпаны попытки)."""
        job = await self.get_by_id(job_id)
        if job is None:
            return

        if (job.attempts or 0) >= _MAX_ATTEMPTS:
            job.status = PipelineJobStatus.failed
            job.locked_until = None
            job.next_retry_at = None
        else:
            job.status = PipelineJobStatus.pending
            job.locked_until = None
            job.next_retry_at = _utcnow() + _backoff(job.attempts or 1)

        job.last_error = error[:2000]
        await self.session.flush()

    async def set_progress_message_id(self, job_id: int, message_id: int) -> None:
        """Сохранить message_id прогресс-сообщения для редактирования из media_worker."""
        await self.session.execute(
            update(self.model).where(self.model.id == job_id).values(progress_message_id=message_id)
        )
