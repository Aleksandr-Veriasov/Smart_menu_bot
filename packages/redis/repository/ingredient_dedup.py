from packages.redis.lock_repository import maybe_await
from packages.redis.repository.base import BaseRedisRepository


class IngredientDedupCacheRepository(BaseRedisRepository):
    """Пары ингредиентов, отклонённые админом при ИИ-поиске дублей — не предлагать повторно."""

    @staticmethod
    def _pair_key(id_a: int, id_b: int) -> str:
        lo, hi = sorted((id_a, id_b))
        return f"{lo}:{hi}"

    async def reject(self, id_a: int, id_b: int) -> None:
        """Запомнить пару как отклонённую на ttl.DUP_REJECTED_PAIRS."""
        key = self.keys.ingredient_dup_rejected_pairs()
        await maybe_await(self.redis.sadd(key, self._pair_key(id_a, id_b)))
        await maybe_await(self.redis.expire(key, self.ttl.DUP_REJECTED_PAIRS))

    async def list_rejected(self) -> set[str]:
        """Все отклонённые пары как строки "id_lo:id_hi"."""
        raw = await maybe_await(self.redis.smembers(self.keys.ingredient_dup_rejected_pairs()))
        return {str(x) for x in raw}

    @classmethod
    def is_rejected_pair(cls, id_a: int, id_b: int, rejected: set[str]) -> bool:
        return cls._pair_key(id_a, id_b) in rejected
