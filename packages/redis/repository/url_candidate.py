import json

from packages.redis.repository.base import BaseRedisRepository


class UrlCandidateCacheRepository(BaseRedisRepository):

    async def get(self, *, user_id: int, sid: str) -> dict:
        """Получить состояние кандидата по URL для пользователя."""
        raw = await self.redis.get(self.keys.user_url_candidate_state(user_id, sid))
        if raw is None:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def set(self, *, user_id: int, sid: str, payload: dict) -> None:
        """Сохранить состояние кандидата по URL для пользователя."""
        value = json.dumps(payload, ensure_ascii=False)
        await self.redis.setex(self.keys.user_url_candidate_state(user_id, sid), self.ttl.RECIPE_ACTION, value)

    async def set_merge(self, *, user_id: int, sid: str, patch: dict) -> dict:
        """Обновить отдельные поля состояния кандидата, не затрагивая остальные."""
        state = await self.get(user_id=user_id, sid=sid)
        state.update(patch or {})
        await self.set(user_id=user_id, sid=sid, payload=state)
        return state

    async def delete(self, *, user_id: int, sid: str) -> None:
        """Удалить состояние кандидата после завершения сценария выбора рецепта."""
        await self.redis.delete(self.keys.user_url_candidate_state(user_id, sid))
