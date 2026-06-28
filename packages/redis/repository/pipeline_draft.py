import json

from packages.redis.data_models import PipelineDraft
from packages.redis.lock_repository import maybe_await
from packages.redis.repository.base import BaseRedisRepository


class PipelineDraftCacheRepository(BaseRedisRepository):

    async def get(self, user_id: int, pipeline_id: int) -> PipelineDraft | None:
        """Возвращает черновик пайплайна или None."""
        raw = await self.redis.get(self.keys.user_pipeline_draft(user_id, pipeline_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return PipelineDraft.from_dict(data)
        except Exception:
            return None

    async def set(self, user_id: int, pipeline_id: int, payload: PipelineDraft | dict) -> None:
        """Сохраняет черновик пайплайна."""
        if isinstance(payload, PipelineDraft):
            payload = payload.to_dict()
        value = json.dumps(payload, ensure_ascii=False)
        await self.redis.setex(
            self.keys.user_pipeline_draft(user_id, pipeline_id),
            self.ttl.PIPELINE_DRAFT,
            value,
        )
        await maybe_await(self.redis.sadd(self.keys.user_pipeline_ids(user_id), pipeline_id))
        await maybe_await(self.redis.expire(self.keys.user_pipeline_ids(user_id), self.ttl.PIPELINE_DRAFT))

    async def delete(self, user_id: int, pipeline_id: int) -> None:
        """Удаляет черновик пайплайна."""
        await self.redis.delete(self.keys.user_pipeline_draft(user_id, pipeline_id))
        await maybe_await(self.redis.srem(self.keys.user_pipeline_ids(user_id), pipeline_id))

    async def list_ids(self, user_id: int) -> list[int]:
        """Возвращает список активных pipeline_id пользователя."""
        raw = await maybe_await(self.redis.smembers(self.keys.user_pipeline_ids(user_id)))
        return [int(x) for x in raw if isinstance(x, (int | str)) and str(x).isdigit()]
