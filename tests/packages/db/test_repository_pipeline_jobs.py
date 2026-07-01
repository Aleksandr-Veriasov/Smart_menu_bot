"""Тесты для PipelineJobRepository."""

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import PipelineJobStatus
from packages.db.repository import PipelineJobRepository, UserRepository
from packages.db.schemas import UserCreate

_USER_ID = 100001
_CHAT_ID = -100500
_MESSAGE_ID = 999001
_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


async def _make_user(session: AsyncSession) -> int:
    user = await UserRepository(session).create(UserCreate(id=_USER_ID, username="pipeline_test_user"))
    return int(user.id)


class TestPipelineJobRepositoryEnqueue:
    async def test_enqueue_creates_job(self, db_session: AsyncSession) -> None:
        """enqueue создаёт запись со статусом pending и нужными полями."""
        user_id = await _make_user(db_session)
        repo = PipelineJobRepository(db_session)

        job = await repo.enqueue(
            chat_id=_CHAT_ID,
            message_id=_MESSAGE_ID,
            user_id=user_id,
            url=_URL,
        )

        assert job.id is not None
        assert job.chat_id == _CHAT_ID
        assert job.message_id == _MESSAGE_ID
        assert job.user_id == user_id
        assert job.url == _URL
        assert job.status == PipelineJobStatus.pending
        assert job.attempts == 0
        assert job.locked_until is None
        assert job.next_retry_at is None
        assert job.created_at is not None

    async def test_enqueue_idempotent(self, db_session: AsyncSession) -> None:
        """Повторный enqueue с тем же (chat_id, message_id) возвращает существующую запись."""
        user_id = await _make_user(db_session)
        repo = PipelineJobRepository(db_session)

        job1 = await repo.enqueue(chat_id=_CHAT_ID, message_id=_MESSAGE_ID, user_id=user_id, url=_URL)
        job2 = await repo.enqueue(chat_id=_CHAT_ID, message_id=_MESSAGE_ID, user_id=user_id, url=_URL)

        assert job1.id == job2.id
        assert await repo.count() == 1


class TestPipelineJobRepositoryClaim:
    async def test_claim_transitions_to_running(self, db_session: AsyncSession) -> None:
        """claim переводит задачу в running, увеличивает attempts, ставит locked_until."""
        user_id = await _make_user(db_session)
        repo = PipelineJobRepository(db_session)
        await repo.enqueue(chat_id=_CHAT_ID, message_id=_MESSAGE_ID, user_id=user_id, url=_URL)

        jobs = await repo.claim(batch_size=1)

        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == PipelineJobStatus.running
        assert job.attempts == 1
        assert job.locked_until is not None
        assert job.locked_until.tzinfo is not None

    async def test_claim_empty_when_no_pending(self, db_session: AsyncSession) -> None:
        """claim возвращает пустой список если нет pending задач."""
        repo = PipelineJobRepository(db_session)

        jobs = await repo.claim()

        assert jobs == []


class TestPipelineJobRepositoryAck:
    async def test_ack_marks_done(self, db_session: AsyncSession) -> None:
        """ack переводит задачу в done и снимает блокировку."""
        user_id = await _make_user(db_session)
        repo = PipelineJobRepository(db_session)
        await repo.enqueue(chat_id=_CHAT_ID, message_id=_MESSAGE_ID, user_id=user_id, url=_URL)
        jobs = await repo.claim()
        job_id = jobs[0].id

        await repo.ack(job_id)
        await db_session.flush()

        done = await repo.get_by_id(job_id)
        assert done is not None
        assert done.status == PipelineJobStatus.done
        assert done.locked_until is None
        assert done.next_retry_at is None
        assert done.last_error is None


class TestPipelineJobRepositoryNack:
    async def test_nack_schedules_retry(self, db_session: AsyncSession) -> None:
        """nack при первой ошибке возвращает в pending с next_retry_at."""
        user_id = await _make_user(db_session)
        repo = PipelineJobRepository(db_session)
        await repo.enqueue(chat_id=_CHAT_ID, message_id=_MESSAGE_ID, user_id=user_id, url=_URL)
        jobs = await repo.claim()
        job_id = jobs[0].id

        await repo.nack(job_id, error="download failed")

        job = await repo.get_by_id(job_id)
        assert job is not None
        assert job.status == PipelineJobStatus.pending
        assert job.next_retry_at is not None
        assert job.next_retry_at.tzinfo is not None
        assert job.last_error == "download failed"
        assert job.locked_until is None

    async def test_nack_marks_failed_after_max_attempts(self, db_session: AsyncSession) -> None:
        """nack после 5 попыток ставит статус failed."""
        from sqlalchemy import update

        from packages.db.models.pipeline import PipelineJob

        user_id = await _make_user(db_session)
        repo = PipelineJobRepository(db_session)
        job0 = await repo.enqueue(chat_id=_CHAT_ID, message_id=_MESSAGE_ID, user_id=user_id, url=_URL)
        job0_id = job0.id

        for _ in range(5):
            jobs = await repo.claim()
            if not jobs:
                await db_session.execute(
                    update(PipelineJob).where(PipelineJob.id == job0_id).values(next_retry_at=None)
                )
                await db_session.flush()
                jobs = await repo.claim()
            await repo.nack(jobs[0].id, error="permanent error")

        job = await repo.get_by_id(job0_id)
        assert job is not None
        assert job.status == PipelineJobStatus.failed
        assert job.last_error == "permanent error"


class TestPipelineJobRepositorySetProgressMessageId:
    async def test_set_progress_message_id(self, db_session: AsyncSession) -> None:
        """set_progress_message_id сохраняет message_id для прогресс-сообщения."""
        user_id = await _make_user(db_session)
        repo = PipelineJobRepository(db_session)
        job = await repo.enqueue(chat_id=_CHAT_ID, message_id=_MESSAGE_ID, user_id=user_id, url=_URL)

        await repo.set_progress_message_id(job.id, 42)
        await db_session.flush()

        updated = await repo.get_by_id(job.id)
        assert updated is not None
        assert updated.progress_message_id == 42
