import json

from redis.asyncio import Redis

from packages.redis import ttl
from packages.redis.keys import RedisKeys


class UrlCandidateCacheRepository:

    @classmethod
    async def get(cls, r: Redis, *, user_id: int, sid: str) -> dict:
        """Получить состояние кандидата по URL для пользователя."""
        raw = await r.get(RedisKeys.user_url_candidate_state(user_id, sid))
        if raw is None:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    async def set(cls, r: Redis, *, user_id: int, sid: str, payload: dict) -> None:
        """Сохранить состояние кандидата по URL для пользователя."""
        value = json.dumps(payload, ensure_ascii=False)
        await r.setex(RedisKeys.user_url_candidate_state(user_id, sid), ttl.RECIPE_ACTION, value)

    @classmethod
    async def set_merge(cls, r: Redis, *, user_id: int, sid: str, patch: dict) -> dict:
        """Обновить отдельные поля состояния кандидата, не затрагивая остальные."""
        state = await cls.get(r, user_id=user_id, sid=sid)
        state.update(patch or {})
        await cls.set(r, user_id=user_id, sid=sid, payload=state)
        return state

    @classmethod
    async def delete(cls, r: Redis, *, user_id: int, sid: str) -> None:
        """Удалить состояние кандидата после завершения сценария выбора рецепта."""
        await r.delete(RedisKeys.user_url_candidate_state(user_id, sid))
