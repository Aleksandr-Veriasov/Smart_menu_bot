from redis.asyncio import Redis

from packages.redis.data_models import PipelineDraft
from packages.redis.repository import PipelineDraftCacheRepository


class PipelineDraftStore:
    """Хранилище черновиков пайплайна обработки видео для конкретного пользователя."""

    def __init__(self, redis: Redis, user_id: int) -> None:
        self._repo = PipelineDraftCacheRepository(redis)
        self.user_id = user_id

    async def get(self, pipeline_id: int) -> PipelineDraft | None:
        """Возвращает черновик пайплайна или None, если он не найден."""
        return await self._repo.get(self.user_id, pipeline_id)

    async def set(self, pipeline_id: int, draft: PipelineDraft) -> None:
        """Сохраняет черновик пайплайна."""
        await self._repo.set(self.user_id, pipeline_id, draft)

    async def delete(self, pipeline_id: int) -> None:
        """Удаляет черновик пайплайна после завершения сценария сохранения."""
        await self._repo.delete(self.user_id, pipeline_id)
