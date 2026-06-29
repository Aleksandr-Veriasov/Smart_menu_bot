from collections.abc import Iterable

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from packages.db.models import Ingredient, RecipeIngredient
from packages.schemas.ingredient import DupGroup

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

    async def list_page(self, *, offset: int, limit: int, q: str) -> tuple[list[Ingredient], int]:
        """Вернуть страницу ингредиентов с общим количеством. Поиск по имени если q задан."""
        base = select(self.model)
        if q:
            base = base.where(self.model.name.ilike(f"%{q}%"))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.options(joinedload(self.model.recipes)).order_by(self.model.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all()), int(total)

    async def get_by_name_excluding(self, name: str, exclude_id: int) -> Ingredient | None:
        """Найти ингредиент по имени, исключая указанный id (для проверки дублей при обновлении)."""
        stmt = select(self.model).where(self.model.name == name, self.model.id != exclude_id)
        return await self.session.scalar(stmt)

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

    async def find_dup_groups(self) -> list[DupGroup]:
        """Группы ингредиентов с одинаковым LOWER(name)."""
        rows = (
            await self.session.execute(
                select(
                    func.lower(self.model.name).label("lower_name"),
                    func.count(self.model.id).label("cnt"),
                )
                .group_by(func.lower(self.model.name))
                .having(func.count(self.model.id) > 1)
                .order_by(func.lower(self.model.name))
            )
        ).all()

        if not rows:
            return []

        lower_names = [r.lower_name for r in rows]
        variants_rows = (
            await self.session.execute(
                select(
                    self.model.id,
                    self.model.name,
                    func.count(RecipeIngredient.recipe_id).label("recipe_count"),
                )
                .outerjoin(RecipeIngredient, RecipeIngredient.ingredient_id == self.model.id)
                .where(func.lower(self.model.name).in_(lower_names))
                .group_by(self.model.id, self.model.name)
                .order_by(func.lower(self.model.name), func.count(RecipeIngredient.recipe_id).desc())
            )
        ).all()

        groups: dict[str, list[tuple[int, str, int]]] = {}
        for row in variants_rows:
            key = row.name.lower()
            groups.setdefault(key, []).append((row.id, row.name, row.recipe_count))

        return [DupGroup(lower_name=k, variants=v) for k, v in groups.items()]

    async def merge_duplicate(self, canonical_id: int, duplicate_id: int) -> dict:
        """Перевесить RecipeIngredient с дубля на canonical, удалить дубль."""
        dup_recipe_ids = (
            (
                await self.session.execute(
                    select(RecipeIngredient.recipe_id).where(RecipeIngredient.ingredient_id == duplicate_id)
                )
            )
            .scalars()
            .all()
        )

        existing_canonical = set(
            (
                await self.session.execute(
                    select(RecipeIngredient.recipe_id).where(RecipeIngredient.ingredient_id == canonical_id)
                )
            )
            .scalars()
            .all()
        )

        conflict_recipe_ids = [rid for rid in dup_recipe_ids if rid in existing_canonical]
        remap_recipe_ids = [rid for rid in dup_recipe_ids if rid not in existing_canonical]

        if remap_recipe_ids:
            await self.session.execute(
                update(RecipeIngredient)
                .where(
                    RecipeIngredient.ingredient_id == duplicate_id,
                    RecipeIngredient.recipe_id.in_(remap_recipe_ids),
                )
                .values(ingredient_id=canonical_id)
            )

        await self.session.execute(delete(RecipeIngredient).where(RecipeIngredient.ingredient_id == duplicate_id))

        dup = await self.session.get(self.model, duplicate_id)
        dup_name = dup.name if dup else str(duplicate_id)
        canonical = await self.session.get(self.model, canonical_id)
        canonical_name = canonical.name if canonical else str(canonical_id)

        if dup:
            await self.session.delete(dup)

        return {
            "canonical_id": canonical_id,
            "canonical_name": canonical_name,
            "dup_name": dup_name,
            "remapped": len(remap_recipe_ids),
            "dropped": len(conflict_recipe_ids),
        }
