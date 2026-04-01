import logging
from collections.abc import Iterable
from typing import Any, Generic, TypeVar

import sqlalchemy as sa
from sqlalchemy import desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import ScalarResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import Select

from packages.db.models import (
    BroadcastCampaign,
    BroadcastCampaignStatus,
    BroadcastMessage,
    BroadcastMessageStatus,
    Category,
    Ingredient,
    Recipe,
    RecipeIngredient,
    RecipeUser,
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
    async def create_basic(cls, session: AsyncSession, title: str, description: str | None) -> Recipe:
        recipe = cls.model(
            title=title,
            description=description,
        )
        session.add(recipe)
        await session.flush()
        await session.refresh(recipe)
        return recipe

    @classmethod
    async def create(cls, session: AsyncSession, recipe_create: RecipeCreate) -> Recipe:
        data = recipe_create.model_dump(exclude_unset=True, exclude={"ingredient_ids"})
        user_id = data.pop("user_id", None)
        category_id = data.pop("category_id", None)
        recipe = cls.model(**data)
        session.add(recipe)
        await session.flush()  # получим PK/дефолты, но без коммита
        if user_id is not None and category_id is not None:
            await RecipeUserRepository.link_user(
                session,
                int(recipe.id),
                int(user_id),
                int(category_id),
            )
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
    async def update_category(
        cls,
        session: AsyncSession,
        recipe_id: int,
        user_id: int,
        category_id: int,
    ) -> str | None:
        statement = (
            update(RecipeUser)
            .where(
                RecipeUser.recipe_id == recipe_id,
                RecipeUser.user_id == user_id,
            )
            .values(category_id=category_id)
            .returning(RecipeUser.recipe_id)
        )
        result = await session.execute(statement)
        row = result.scalar_one_or_none()
        logger.debug(f"Рецепт {recipe_id} обновлён: category_id={category_id}, row={row}")
        if row is None:
            raise ValueError("Рецепт не найден")
        return await cls.get_name_by_id(session, recipe_id)

    @classmethod
    async def update_title(cls, session: AsyncSession, recipe_id: int, title: str) -> None:
        statement = update(cls.model).where(cls.model.id == recipe_id).values(title=title)
        result = await session.execute(statement)
        if result.rowcount == 0:
            raise ValueError("Рецепт не найден")
        logger.debug(f"👉 Название рецепта {recipe_id} обновлено на: {title}")

    @classmethod
    async def update_last_used_at(cls, session: AsyncSession, recipe_id: int) -> None:
        statement = update(cls.model).where(cls.model.id == recipe_id).values(last_used_at=func.now())
        await session.execute(statement)

    @classmethod
    async def get_count_by_user(cls, session: AsyncSession, user_id: int) -> int:
        statement = (
            select(func.count(Recipe.id))
            .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
            .where(RecipeUser.user_id == user_id)
        )
        result = await session.execute(statement)
        count = result.scalar_one_or_none()
        return count or 0

    @classmethod
    async def get_recipes_id_by_category(cls, session: AsyncSession, user_id: int, category_id: int) -> list[int]:
        statement: Select[tuple[int]] = (
            select(Recipe.id)
            .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
            .where(RecipeUser.user_id == user_id, RecipeUser.category_id == category_id)
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
            .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
            .where(RecipeUser.user_id == user_id, RecipeUser.category_id == category_id)
            .order_by(Recipe.id)
        )
        result = await session.execute(statement)
        rows = result.all()
        return [{"id": int(row.id), "title": str(row.title)} for row in rows]

    @classmethod
    async def get_ids_and_titles_by_ids(
        cls,
        session: AsyncSession,
        recipe_ids: list[int],
    ) -> list[dict[str, int | str]]:
        """
        Возвращает рецепты по списку id в виде [{"id": ..., "title": ...}].
        """
        if not recipe_ids:
            return []
        statement = select(Recipe.id, Recipe.title).where(Recipe.id.in_(recipe_ids))
        result = await session.execute(statement)
        rows = result.all()
        return [{"id": int(row.id), "title": str(row.title)} for row in rows]

    @classmethod
    async def get_public_recipes_ids_and_titles_by_category(
        cls,
        session: AsyncSession,
        category_id: int,
        *,
        exclude_user_id: int | None = None,
    ) -> list[dict[str, int | str]]:
        """
        Возвращает все рецепты по категории из всей базы:
        - только рецепты, у которых есть видео;
        - исключаем рецепты, уже связанные с `exclude_user_id` (если передан);
        - если к одному видео привязано несколько рецептов, берём самый новый (по max(recipe.id)).
        """
        video_key = func.coalesce(func.nullif(Video.original_url, ""), func.nullif(Video.video_url, ""))
        filters = [
            RecipeUser.category_id == int(category_id),
            video_key.is_not(None),
        ]
        if exclude_user_id is not None:
            filters.append(
                Recipe.id.notin_(select(RecipeUser.recipe_id).where(RecipeUser.user_id == int(exclude_user_id)))
            )

        latest_by_video_subq = (
            select(func.max(Recipe.id).label("recipe_id"))
            .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
            .join(Video, Video.recipe_id == Recipe.id)
            .where(*filters)
            .group_by(video_key)
            .subquery()
        )

        statement = (
            select(Recipe.id, Recipe.title)
            .join(latest_by_video_subq, latest_by_video_subq.c.recipe_id == Recipe.id)
            .order_by(Recipe.id.desc())
        )
        result = await session.execute(statement)
        rows = result.all()
        return [{"id": int(row.id), "title": str(row.title)} for row in rows]

    @classmethod
    async def search_ids_and_titles_by_title(
        cls, session: AsyncSession, user_id: int, query: str
    ) -> list[dict[str, int | str]]:
        """
        Ищет рецепты пользователя по названию.
        """
        pattern = f"%{query}%"
        statement = (
            select(Recipe.id, Recipe.title)
            .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
            .where(RecipeUser.user_id == user_id, Recipe.title.ilike(pattern))
            .order_by(Recipe.id)
        )
        result = await session.execute(statement)
        rows = result.all()
        return [{"id": int(row.id), "title": str(row.title)} for row in rows]

    @classmethod
    async def search_ids_and_titles_by_ingredient(
        cls, session: AsyncSession, user_id: int, query: str
    ) -> list[dict[str, int | str]]:
        """
        Ищет рецепты пользователя по ингредиенту.
        """
        pattern = f"%{query}%"
        statement = (
            select(Recipe.id, Recipe.title)
            .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
            .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
            .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
            .where(RecipeUser.user_id == user_id, Ingredient.name.ilike(pattern))
            .distinct()
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
    async def get_category_id_by_recipe_id(cls, session: AsyncSession, recipe_id: int, user_id: int) -> int | None:
        """
        Получает ID категории по ID рецепта и пользователя.
        """
        statement = select(RecipeUser.category_id).where(
            RecipeUser.recipe_id == recipe_id,
            RecipeUser.user_id == user_id,
        )
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
        rows = result.scalars().all()
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
            .join(RecipeUser, RecipeUser.category_id == cls.model.id)
            .where(RecipeUser.user_id == user_id)
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
    async def get_by_original_url(cls, session: AsyncSession, original_url: str) -> Video | None:
        statement = (
            select(cls.model).where(cls.model.original_url == original_url).order_by(cls.model.id.desc()).limit(1)
        )
        result = await session.execute(statement)
        return result.scalars().first()

    @classmethod
    async def get_all_by_original_url(cls, session: AsyncSession, original_url: str, *, limit: int = 20) -> list[Video]:
        statement = select(cls.model).where(cls.model.original_url == original_url).order_by(cls.model.id.desc())
        if limit and limit > 0:
            statement = statement.limit(int(limit))
        result = await session.execute(statement)
        return list(result.scalars().all())

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        video_url: str,
        recipe_id: int,
        *,
        original_url: str | None = None,
    ) -> Video:
        video = cls.model(video_url=video_url, recipe_id=recipe_id, original_url=original_url)
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


class RecipeUserRepository(BaseRepository[RecipeUser]):
    model = RecipeUser

    @classmethod
    async def link_user(cls, session: AsyncSession, recipe_id: int, user_id: int, category_id: int) -> None:
        stmt = (
            pg_insert(RecipeUser)
            .values(
                {
                    "recipe_id": int(recipe_id),
                    "user_id": int(user_id),
                    "category_id": int(category_id),
                }
            )
            .on_conflict_do_nothing(
                index_elements=[RecipeUser.recipe_id, RecipeUser.user_id],
            )
        )
        await session.execute(stmt)

    @classmethod
    async def upsert_user_link(
        cls,
        session: AsyncSession,
        recipe_id: int,
        user_id: int,
        category_id: int,
    ) -> bool:
        """
        Создаёт связь рецепт-пользователь или обновляет category_id для существующей.
        Возвращает True, если связь была создана, иначе False.
        """
        stmt = (
            pg_insert(RecipeUser)
            .values(
                {
                    "recipe_id": int(recipe_id),
                    "user_id": int(user_id),
                    "category_id": int(category_id),
                }
            )
            .on_conflict_do_update(
                index_elements=[RecipeUser.recipe_id, RecipeUser.user_id],
                set_={"category_id": int(category_id)},
            )
            .returning(sa.literal_column("xmax = 0"))
        )
        result = await session.execute(stmt)
        return bool(result.scalar_one())

    @classmethod
    async def unlink_user(cls, session: AsyncSession, recipe_id: int, user_id: int) -> None:
        statement = sa.delete(RecipeUser).where(RecipeUser.recipe_id == recipe_id, RecipeUser.user_id == user_id)
        await session.execute(statement)

    @classmethod
    async def is_linked(cls, session: AsyncSession, recipe_id: int, user_id: int) -> bool:
        statement = select(func.count(RecipeUser.id)).where(
            RecipeUser.recipe_id == recipe_id, RecipeUser.user_id == user_id
        )
        result = await session.execute(statement)
        return (result.scalar_one_or_none() or 0) > 0

    @classmethod
    async def get_any_category_id(cls, session: AsyncSession, recipe_id: int) -> int | None:
        statement = select(RecipeUser.category_id).where(RecipeUser.recipe_id == recipe_id).limit(1)
        result = await session.execute(statement)
        return result.scalar_one_or_none()


class BroadcastRepository:
    @staticmethod
    async def build_outbox_all_users(session: AsyncSession, *, campaign_id: int) -> None:
        """
        Построить outbox для кампании по аудитории all_users.
        Дубликаты (campaign_id, chat_id) игнорируются.
        """
        insert_stmt = pg_insert(BroadcastMessage).from_select(
            ["campaign_id", "chat_id", "status", "attempts"],
            select(
                sa.literal(int(campaign_id)),
                User.id,
                sa.literal(BroadcastMessageStatus.pending),
                sa.literal(0),
            ),
        )
        stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=[BroadcastMessage.campaign_id, BroadcastMessage.chat_id]
        )
        await session.execute(stmt)

    @staticmethod
    async def list_campaigns(session: AsyncSession, *, limit: int) -> list[BroadcastCampaign]:
        stmt = select(BroadcastCampaign).order_by(desc(BroadcastCampaign.id)).limit(max(1, min(200, int(limit))))
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def create_campaign(
        session: AsyncSession,
        *,
        name: str,
        status,
        audience_type,
        audience_params_json: str | None,
        text: str,
        parse_mode: str,
        disable_web_page_preview: bool,
        reply_markup_json: str | None,
        photo_file_id: str | None,
        photo_url: str | None,
        scheduled_at,
    ) -> BroadcastCampaign:
        campaign = BroadcastCampaign(
            name=name,
            status=status,
            audience_type=audience_type,
            audience_params_json=audience_params_json,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup_json=reply_markup_json,
            photo_file_id=photo_file_id,
            photo_url=photo_url,
            scheduled_at=scheduled_at,
        )
        session.add(campaign)
        await session.flush()
        await session.refresh(campaign)
        return campaign

    @staticmethod
    async def get_campaign_or_none(session: AsyncSession, campaign_id: int) -> BroadcastCampaign | None:
        res = await session.execute(select(BroadcastCampaign).where(BroadcastCampaign.id == int(campaign_id)))
        return res.scalar_one_or_none()

    @classmethod
    async def update_campaign(
        cls,
        session: AsyncSession,
        *,
        campaign_id: int,
        changes: dict[str, Any],
    ) -> BroadcastCampaign:
        campaign = await cls.get_campaign_or_none(session, campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        # Разрешаем перезапись кампании только пока не было фактических отправок.
        if int(campaign.sent_count or 0) > 0 or int(campaign.failed_count or 0) > 0:
            raise ValueError("Campaign already has deliveries; create a new campaign instead")
        if campaign.status == BroadcastCampaignStatus.completed:
            raise ValueError("Completed campaign is immutable; create a new campaign instead")

        for field, value in changes.items():
            setattr(campaign, field, value)

        await session.flush()
        await session.refresh(campaign)
        return campaign

    @classmethod
    async def queue_campaign(cls, session: AsyncSession, *, campaign_id: int) -> BroadcastCampaign:
        campaign = await cls.get_campaign_or_none(session, campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status not in (
            BroadcastCampaignStatus.draft,
            BroadcastCampaignStatus.paused,
            BroadcastCampaignStatus.failed,
        ):
            raise ValueError(f"Cannot queue from status={campaign.status.value}")
        campaign.status = BroadcastCampaignStatus.queued
        campaign.last_error = None
        campaign.finished_at = None
        await session.flush()
        await session.refresh(campaign)
        return campaign

    @classmethod
    async def pause_campaign(cls, session: AsyncSession, *, campaign_id: int) -> BroadcastCampaign:
        campaign = await cls.get_campaign_or_none(session, campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status != BroadcastCampaignStatus.running:
            raise ValueError(f"Cannot pause from status={campaign.status.value}")
        campaign.status = BroadcastCampaignStatus.paused
        await session.flush()
        await session.refresh(campaign)
        return campaign

    @classmethod
    async def resume_campaign(cls, session: AsyncSession, *, campaign_id: int, now_utc) -> BroadcastCampaign:
        campaign = await cls.get_campaign_or_none(session, campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status != BroadcastCampaignStatus.paused:
            raise ValueError(f"Cannot resume from status={campaign.status.value}")
        campaign.status = BroadcastCampaignStatus.running
        if campaign.started_at is None:
            campaign.started_at = now_utc
        await session.flush()
        await session.refresh(campaign)
        return campaign

    @classmethod
    async def cancel_campaign(cls, session: AsyncSession, *, campaign_id: int, now_utc) -> BroadcastCampaign:
        campaign = await cls.get_campaign_or_none(session, campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.status in (BroadcastCampaignStatus.completed, BroadcastCampaignStatus.cancelled):
            return campaign
        campaign.status = BroadcastCampaignStatus.cancelled
        campaign.finished_at = now_utc
        await session.flush()
        await session.refresh(campaign)
        return campaign

    @staticmethod
    async def list_messages(session: AsyncSession, *, campaign_id: int, limit: int) -> list[BroadcastMessage]:
        stmt = (
            select(BroadcastMessage)
            .where(BroadcastMessage.campaign_id == int(campaign_id))
            .order_by(desc(BroadcastMessage.id))
            .limit(max(1, min(500, int(limit))))
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())
