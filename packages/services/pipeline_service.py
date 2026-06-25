from packages.db.models.pipeline import PipelineJob
from packages.db.repository import PipelineJobRepository
from packages.services.base import BaseService


class PipelineService(BaseService):
    async def enqueue(self, *, chat_id: int, message_id: int, user_id: int, url: str) -> int:
        """Поставить задачу в очередь. Идемпотентно: повторный вызов с тем же (chat_id, message_id) вернёт существующий job_id."""
        async with self.db.session() as session:
            job = await PipelineJobRepository(session).enqueue(
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                url=url,
            )
            return int(job.id)

    async def set_progress_message_id(self, job_id: int, progress_message_id: int) -> None:
        """Сохранить message_id прогресс-сообщения, чтобы media_worker мог редактировать его по ходу обработки."""
        async with self.db.session() as session:
            await PipelineJobRepository(session).set_progress_message_id(job_id, progress_message_id)

    async def claim(self, *, batch_size: int = 1) -> list[int]:
        """Атомарно забрать до batch_size pending-задач (FOR UPDATE SKIP LOCKED). Возвращает список job_id."""
        async with self.db.session() as session:
            jobs = await PipelineJobRepository(session).claim(batch_size=batch_size)
            return [int(job.id) for job in jobs]

    async def get_by_id(self, job_id: int) -> PipelineJob | None:
        """Вернуть job по id или None если не найден."""
        async with self.db.session() as session:
            return await PipelineJobRepository(session).get_by_id(job_id)

    async def ack(self, job_id: int) -> None:
        """Пометить задачу как успешно выполненную (статус → done)."""
        async with self.db.session() as session:
            await PipelineJobRepository(session).ack(job_id)

    async def nack(self, job_id: int, *, error: str) -> None:
        """Вернуть задачу в очередь с backoff или пометить failed после исчерпания попыток."""
        async with self.db.session() as session:
            await PipelineJobRepository(session).nack(job_id, error=error)
