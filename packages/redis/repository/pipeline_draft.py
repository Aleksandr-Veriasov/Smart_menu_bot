import json

from redis.asyncio import Redis

from packages.redis import ttl
from packages.redis.data_models import PipelineDraft
from packages.redis.keys import RedisKeys
from packages.redis.lock_repository import maybe_await


class PipelineDraftCacheRepository:

    @classmethod
    async def get(cls, r: Redis, user_id: int, pipeline_id: int) -> PipelineDraft | None:
        """Возвращает черновик пайплайна или None."""
        raw = await r.get(RedisKeys.user_pipeline_draft(user_id, pipeline_id))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return PipelineDraft.from_dict(data)
        except Exception:
            return None

    @classmethod
    async def set(cls, r: Redis, user_id: int, pipeline_id: int, payload: PipelineDraft | dict) -> None:
        """Сохраняет черновик пайплайна."""
        if isinstance(payload, PipelineDraft):
            payload = payload.to_dict()
        value = json.dumps(payload, ensure_ascii=False)
        await r.setex(
            RedisKeys.user_pipeline_draft(user_id, pipeline_id),
            ttl.PIPELINE_DRAFT,
            value,
        )
        await maybe_await(r.sadd(RedisKeys.user_pipeline_ids(user_id), pipeline_id))
        await maybe_await(r.expire(RedisKeys.user_pipeline_ids(user_id), ttl.PIPELINE_DRAFT))

    @classmethod
    async def delete(cls, r: Redis, user_id: int, pipeline_id: int) -> None:
        """Удаляет черновик пайплайна."""
        await r.delete(RedisKeys.user_pipeline_draft(user_id, pipeline_id))
        await maybe_await(r.srem(RedisKeys.user_pipeline_ids(user_id), pipeline_id))

    @classmethod
    async def list_ids(cls, r: Redis, user_id: int) -> list[int]:
        """Возвращает список активных pipeline_id пользователя."""
        raw = await maybe_await(r.smembers(RedisKeys.user_pipeline_ids(user_id)))
        return [int(x) for x in raw if isinstance(x, (int | str)) and str(x).isdigit()]
