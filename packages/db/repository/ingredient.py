from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from packages.db.models import Ingredient

from .base import BaseRepository


class IngredientRepository(BaseRepository[Ingredient]):
    """Репозиторий для работы с ингредиентами."""

    model = Ingredient

    async def create(self, name: str) -> Ingredient:
        """Создать ингредиент. Raises ValueError если уже существует."""
        ingredient = self.model(name=name)
        self.session.add(ingredient)
        try:
            return await self.save(ingredient)
        except IntegrityError as exc:
            raise ValueError("Ingredient already exists") from exc

    async def get_or_create(self, name: str) -> Ingredient:
        """Вернуть существующий ингредиент по имени или создать новый."""
        existing = await self.get_by_name(name)
        if existing:
            return existing
        return await self.create(name)

    async def get_by_name(self, name: str) -> Ingredient | None:
        """Найти ингредиент по имени."""
        statement = select(self.model).where(self.model.name == name)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def bulk_get_or_create(self, names: Iterable[str]) -> dict[str, int]:
        """Возвращает {name: id} для переданных имён. Устойчива к гонкам благодаря ON CONFLICT DO NOTHING + доп. выборке."""
        norm = [n.strip() for n in names if n and str(n).strip()]
        if not norm:
            return {}

        uniq = list(dict.fromkeys(norm))

        rows = await self.session.execute(select(self.model.id, self.model.name).where(self.model.name.in_(uniq)))
        existing = {name: _id for _id, name in rows.all()}

        to_insert = [n for n in uniq if n not in existing]
        inserted: dict[str, int] = {}

        if to_insert:
            stmt = (
                pg_insert(self.model)
                .values([{"name": n} for n in to_insert])
                .on_conflict_do_nothing(index_elements=[self.model.name])
                .returning(self.model.id, self.model.name)
            )
            res = await self.session.execute(stmt)
            inserted = {name: _id for _id, name in res.all()}

            missing = [n for n in to_insert if n not in inserted]
            if missing:
                res2 = await self.session.execute(
                    select(self.model.id, self.model.name).where(self.model.name.in_(missing))
                )
                inserted.update({name: _id for _id, name in res2.all()})

        return {**existing, **inserted}
