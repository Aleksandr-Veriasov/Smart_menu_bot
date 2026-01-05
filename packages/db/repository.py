from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Generic, TypeVar

from sqlalchemy import desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import ScalarResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import Select

from packages.db.models import (
    Category,
    Ingredient,
    Recipe,
    RecipeIngredient,
    User,
    Video,
)
from packages.db.schemas import (
    CategoryCreate,
    RecipeCreate,
    RecipeUpdate,
    UserCreate,
    UserUpdate,
)

logger = logging.getLogger(__name__)

M = TypeVar("M")  # тип модели


async def fetch_all(session: AsyncSession, stmt: Select[tuple[M]]) -> list[M]:
    res: ScalarResult[M] = await session.scalars(stmt)
    return list(res)


class BaseRepository(Generic[M]):
    model: type[M]  # обязан задать наследник

    @classmethod
    async def get_by_id(cls, session: AsyncSession, id: int) -> M | None:
        return await session.get(cls.model, id)


class UserRepository(BaseRepository[User]):
    model = User

    @classmethod
    async def create(cls, session: AsyncSession, payload: UserCreate) -> User:
        data = payload.model_dump(exclude_unset=True, exclude_none=True)
        user = cls.model(**data)
        session.add(user)
        try:
            await session.flush()  # получаем PK / дефолты
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("User already exists") from exc
        await session.refresh(user)  # подхватить БД-дефолты/триггеры
        return user

    @classmethod
    async def update(cls, session: AsyncSession, user_id: int, payload: UserUpdate) -> User:
        user = await cls.get_by_id(session, user_id)
        if not user:
            raise ValueError("User not found")
        changes = payload.model_dump(exclude_unset=True, exclude_none=True)

        for key, value in changes.items():
            setattr(user, key, value)

        await session.flush()
        await session.refresh(user)
        return user


class RecipeRepository(BaseRepository[Recipe]):
    model = Recipe

    @classmethod
    async def create(cls, session: AsyncSession, recipe_create: RecipeCreate) -> Recipe:
        data = recipe_create.model_dump(exclude_unset=True)
        recipe = cls.model(**data)
        session.add(recipe)
        await session.flush()  # получим PK/дефолты, но без коммита
        await session.refresh(recipe)  # подхватить БД-дефолты/триггеры
        return recipe

    @classmethod
    async def update(cls, session: AsyncSession, recipe_id: int, recipe_update: RecipeUpdate) -> Recipe:
        recipe = await cls.get_by_id(session, recipe_id)
        if not recipe:
            raise ValueError("Recipe not found")
        changes = recipe_update.model_dump(exclude_unset=True)

        for key, value in changes.items():
            setattr(recipe, key, value)

        await session.flush()
        await session.refresh(recipe)
        return recipe

    @classmethod
    async def update_category(cls, session: AsyncSession, recipe_id: int, category_id: int) -> str | None:
        statement = (
            update(cls.model)
            .where(cls.model.id == recipe_id)
            .values(category_id=category_id)
            .returning(cls.model.title)
        )
        result = await session.execute(statement)
        row = result.scalar_one_or_none()
        logger.debug(f"Updated recipe {recipe_id} to category " f"{category_id}, title={row}")
        if row is None:
            raise ValueError("Recipe not found")
        return row

    @classmethod
    async def update_title(cls, session: AsyncSession, recipe_id: int, title: str) -> None:
        statement = update(cls.model).where(cls.model.id == recipe_id).values(title=title)
        result = await session.execute(statement)
        if result.rowcount == 0:
            raise ValueError("Recipe not found")
        logger.debug(f"👉 Updated recipe {recipe_id} title to {title}")

    @classmethod
    async def get_count_by_user(cls, session: AsyncSession, user_id: int) -> int:
        statement = select(func.count(Recipe.id)).where(Recipe.user_id == user_id)
        result = await session.execute(statement)
        count = result.scalar_one_or_none()
        return count or 0

    @classmethod
    async def get_recipes_id_by_category(cls, session: AsyncSession, user_id: int, category_id: int) -> list[int]:
        statement: Select[tuple[int]] = (
            select(Recipe.id)
            .where(Recipe.user_id == user_id, Recipe.category_id == category_id)
            .order_by(desc(Recipe.id))
        )

        return await fetch_all(session, statement)

    @classmethod
    async def get_recipe_with_connections(cls, session: AsyncSession, recipe_id: int) -> Recipe | None:
        """
        Получает рецепт с его ингредиентами и категорией.
        """
        statement = (
            select(Recipe)
            .where(Recipe.id == recipe_id)
            .options(
                joinedload(Recipe.ingredients),
                joinedload(Recipe.category),
                joinedload(Recipe.video),
            )
        )
        result = await session.execute(statement)
        return result.unique().scalars().one_or_none()

    @classmethod
    async def get_all_recipes_ids_and_titles(
        cls, session: AsyncSession, user_id: int, category_id: int
    ) -> list[dict[str, int | str]]:
        """
        Получает все рецепты пользователя с их ID и заголовками.
        """
        statement = (
            select(Recipe.id, Recipe.title)
            .where(Recipe.user_id == user_id, Recipe.category_id == category_id)
            .order_by(Recipe.id)
        )
        result = await session.execute(statement)
        rows = result.all()
        return [{"id": int(row.id), "title": str(row.title)} for row in rows]

    @classmethod
    async def get_name_by_id(cls, session: AsyncSession, recipe_id: int) -> str | None:
        """
        Получает название рецепта по его ID.
        """
        statement = select(Recipe.title).where(Recipe.id == recipe_id)
        result = await session.execute(statement)
        name = result.scalar_one_or_none()
        return name

    @classmethod
    async def delete(cls, session: AsyncSession, recipe_id: int) -> None:
        """
        Удаляет рецепт по его ID.
        """
        recipe = await cls.get_by_id(session, recipe_id)
        if not recipe:
            raise ValueError("Recipe not found")
        await session.delete(recipe)

    @classmethod
    async def get_category_id_by_recipe_id(cls, session: AsyncSession, recipe_id: int) -> int | None:
        """
        Получает ID категории по ID рецепта.
        """
        statement = select(Recipe.category_id).where(Recipe.id == recipe_id)
        result = await session.execute(statement)
        category_id = result.scalar_one_or_none()
        return category_id


class CategoryRepository(BaseRepository[Category]):
    model = Category

    @classmethod
    async def create(cls, session: AsyncSession, payload: CategoryCreate) -> Category:
        data = payload.model_dump(exclude_unset=True)
        category = cls.model(**data)
        session.add(category)
        try:
            await session.flush()  # получим PK / дефолты
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("Category already exists") from exc
        await session.refresh(category)  # подхватить БД-дефолты/триггеры
        return category

    @classmethod
    async def get_id_and_name_by_slug(cls, session: AsyncSession, slug: str) -> tuple[int, str]:
        statement = select(cls.model.id, cls.model.name).where(cls.model.slug == slug)
        result = await session.execute(statement)
        row = result.first()
        if row is None:
            raise ValueError("Category not found")
        return (row.id, row.name)

    @classmethod
    async def get_all_name_and_slug(cls, session: AsyncSession) -> list[dict[str, str]]:
        statement = select(
            cls.model.name.label("name"),
            cls.model.slug.label("slug"),
        ).order_by(cls.model.id)
        result = await session.execute(statement)
        rows = result.all()
        return [{"name": row.name, "slug": row.slug} for row in rows]

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list[dict[str, Any]]:
        statement = select(cls.model).order_by(cls.model.id)
        result = await session.execute(statement)
        rows = result.all()
        return [{"id": row.id, "name": row.name, "slug": row.slug} for row in rows]

    @classmethod
    async def get_id_by_slug(cls, session: AsyncSession, slug: str) -> int:
        statement = select(cls.model.id).where(cls.model.slug == slug)
        result = await session.execute(statement)
        id = result.scalar_one_or_none()
        if id is None:
            raise ValueError("Category not found")
        return id

    @classmethod
    async def get_name_and_slug_by_user_id(cls, session: AsyncSession, user_id: int) -> list[dict[str, str]]:
        statement = (
            select(
                cls.model.name.label("name"),
                cls.model.slug.label("slug"),
            )
            .join(Recipe, Recipe.category_id == cls.model.id)
            .where(Recipe.user_id == user_id)
            .group_by(cls.model.id, cls.model.name, cls.model.slug)
            .order_by(cls.model.id)
        )
        result = await session.execute(statement)
        rows = result.all()
        return [{"name": row.name, "slug": row.slug} for row in rows]


class VideoRepository(BaseRepository[Video]):
    model = Video

    @classmethod
    async def get_video_url(cls, session: AsyncSession, recipe_id: int) -> str | None:
        statement = select(cls.model.video_url).where(cls.model.recipe_id == recipe_id)
        result = await session.execute(statement)
        video_url = result.scalar_one_or_none()
        return video_url

    @classmethod
    async def create(cls, session: AsyncSession, video_url: str, recipe_id: int) -> Video:
        video = cls.model(video_url=video_url, recipe_id=recipe_id)
        session.add(video)
        try:
            await session.flush()  # получим PK / дефолты
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("Video already exists") from exc
        await session.refresh(video)  # подхватить БД-дефолты/триггеры
        return video


class IngredientRepository(BaseRepository[Ingredient]):
    model = Ingredient

    @classmethod
    async def create(cls, session: AsyncSession, name: str) -> Ingredient:
        ingredient = await cls.get_by_name(session, name)
        if not ingredient:
            ingredient = cls.model(name=name)
            session.add(ingredient)
            try:
                await session.flush()  # получим PK / дефолты
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError("Ingredient already exists") from exc
            await session.refresh(ingredient)
        return ingredient

    @classmethod
    async def get_by_name(cls, session: AsyncSession, name: str) -> Ingredient | None:
        statement = select(cls.model).where(cls.model.name == name)
        result = await session.execute(statement)
        ingredient = result.scalar_one_or_none()
        return ingredient

    @classmethod
    async def bulk_get_or_create(cls, session: AsyncSession, names: Iterable[str]) -> dict[str, int]:
        """
        Возвращает {name: id} для переданных имён.
        Отсеивает пустые/дубликаты, создаёт недостающие ингредиенты пачкой.
        Устойчива к гонкам благодаря ON CONFLICT DO NOTHING + доп. выборке.
        """
        norm = [n.strip() for n in names if n and str(n).strip()]
        if not norm:
            return {}

        uniq = list(dict.fromkeys(norm))

        # уже существующие
        rows = await session.execute(select(Ingredient.id, Ingredient.name).where(Ingredient.name.in_(uniq)))
        existing = {name: _id for _id, name in rows.all()}

        to_insert = [n for n in uniq if n not in existing]
        inserted: dict[str, int] = {}

        if to_insert:
            stmt = (
                pg_insert(Ingredient)
                .values([{"name": n} for n in to_insert])
                .on_conflict_do_nothing(index_elements=[Ingredient.name])
                .returning(Ingredient.id, Ingredient.name)
            )
            res = await session.execute(stmt)
            inserted = {name: _id for _id, name in res.all()}

            # те, кто попал в конфликт (вставил кто-то другой), дочитываем
            missing = [n for n in to_insert if n not in inserted]
            if missing:
                res2 = await session.execute(select(Ingredient.id, Ingredient.name).where(Ingredient.name.in_(missing)))
                inserted.update({name: _id for _id, name in res2.all()})

        return {**existing, **inserted}


class RecipeIngredientRepository(BaseRepository[RecipeIngredient]):
    model = RecipeIngredient

    @classmethod
    async def create(cls, session: AsyncSession, recipe_id: int, ingredient_id: int) -> RecipeIngredient:
        recipe_ingredient = cls.model(recipe_id=recipe_id, ingredient_id=ingredient_id)
        session.add(recipe_ingredient)
        try:
            await session.flush()  # получим PK / дефолты
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("RecipeIngredient already exists") from exc
        # подхватить БД-дефолты/триггеры
        await session.refresh(recipe_ingredient)
        return recipe_ingredient

    @classmethod
    async def bulk_link(
        cls,
        session: AsyncSession,
        recipe_id: int,
        ingredient_ids: Iterable[int],
    ) -> None:
        """
        Массово создаёт связи рецепт-ингредиент.
        Дубликаты игнорируются (ON CONFLICT DO NOTHING).
        """
        ids = list({int(i) for i in ingredient_ids if i})
        if not ids:
            return
        values = [{"recipe_id": int(recipe_id), "ingredient_id": i} for i in ids]
        stmt = (
            pg_insert(RecipeIngredient)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[
                    RecipeIngredient.recipe_id,
                    RecipeIngredient.ingredient_id,
                ]
            )
        )
        await session.execute(stmt)
