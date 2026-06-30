import logging

from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import joinedload

from packages.db.models import Ingredient, Recipe, RecipeIngredient, RecipeUser, Video
from packages.db.schemas import RecipeCreate, RecipeUpdate

from .base import BaseRepository, fetch_all
from .recipe_user import RecipeUserRepository

logger = logging.getLogger(__name__)


class RecipeRepository(BaseRepository[Recipe]):
    """Репозиторий для работы с рецептами."""

    model = Recipe

    async def create_basic(self, title: str, description: str | None) -> Recipe:
        """Создать минимальный рецепт без привязки к пользователю и категории."""
        recipe = self.model(title=title, description=description)
        self.session.add(recipe)
        return await self.save(recipe)

    async def create(self, recipe_create: RecipeCreate) -> Recipe:
        """Создать рецепт и привязать к пользователю в категории, если указаны."""
        data = recipe_create.model_dump(exclude_unset=True, exclude={"ingredient_ids"})
        user_id = data.pop("user_id", None)
        category_id = data.pop("category_id", None)
        recipe = self.model(**data)
        self.session.add(recipe)
        await self.session.flush()
        if user_id is not None and category_id is not None:
            await RecipeUserRepository(self.session).link_user(int(recipe.id), int(user_id), int(category_id))
        return await self.save(recipe)

    async def update(self, recipe_id: int, recipe_update: RecipeUpdate) -> Recipe:
        """Обновить поля рецепта из payload."""
        return await self.update_fields(recipe_id, recipe_update.model_dump(exclude_unset=True))

    async def update_category(self, recipe_id: int, user_id: int, category_id: int) -> str | None:
        """Сменить категорию рецепта для пользователя. Возвращает название рецепта."""
        statement = (
            update(RecipeUser)
            .where(RecipeUser.recipe_id == recipe_id, RecipeUser.user_id == user_id)
            .values(category_id=category_id)
            .returning(RecipeUser.recipe_id)
        )
        result = await self.session.execute(statement)
        row = result.scalar_one_or_none()
        logger.debug(f"Рецепт {recipe_id} обновлён: category_id={category_id}, row={row}")
        if row is None:
            raise ValueError("Рецепт не найден")
        return await self.get_name_by_id(recipe_id)

    async def update_title(self, recipe_id: int, title: str) -> None:
        """Обновить заголовок рецепта."""
        await self.update_fields(recipe_id, {"title": title})
        logger.debug(f"Название рецепта {recipe_id} обновлено на: {title}")

    async def update_last_used_at(self, recipe_id: int) -> None:
        """Обновить метку последнего использования рецепта на текущее время."""
        statement = update(self.model).where(self.model.id == recipe_id).values(last_used_at=func.now())
        await self.session.execute(statement)

    async def get_count_by_user(self, user_id: int) -> int:
        """Вернуть количество рецептов пользователя."""
        statement = (
            select(func.count(self.model.id))
            .join(RecipeUser, RecipeUser.recipe_id == self.model.id)
            .where(RecipeUser.user_id == user_id)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() or 0

    async def get_recipes_id_by_category(self, user_id: int, category_id: int) -> list[int]:
        """Вернуть id рецептов пользователя в категории, от новых к старым."""
        statement = (
            select(self.model.id)
            .join(RecipeUser, RecipeUser.recipe_id == self.model.id)
            .where(RecipeUser.user_id == user_id, RecipeUser.category_id == category_id)
            .order_by(desc(self.model.id))
        )
        return await fetch_all(self.session, statement)

    async def get_with_category_for_user(self, recipe_id: int, user_id: int) -> tuple[Recipe, int] | None:
        """Загрузить рецепт пользователя с ингредиентами и видео. Возвращает (recipe, category_id) или None."""
        stmt = (
            select(self.model, RecipeUser.category_id)
            .join(RecipeUser, RecipeUser.recipe_id == self.model.id)
            .where(self.model.id == int(recipe_id), RecipeUser.user_id == int(user_id))
            .options(
                joinedload(self.model.ingredients),
                self._ingredient_links_option(),
                joinedload(self.model.video),
            )
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        return row[0], int(row[1])

    async def get_recipe_with_connections(self, recipe_id: int) -> Recipe | None:
        """Загрузить рецепт вместе с ингредиентами и видео."""
        statement = (
            select(self.model)
            .where(self.model.id == recipe_id)
            .options(
                joinedload(self.model.ingredients),
                joinedload(self.model.video),
            )
        )
        result = await self.session.execute(statement)
        return result.unique().scalars().one_or_none()

    async def get_all_by_user_and_category(self, user_id: int, category_id: int) -> list[Recipe]:
        """Вернуть рецепты пользователя в категории."""
        statement = (
            select(self.model)
            .join(RecipeUser, RecipeUser.recipe_id == self.model.id)
            .where(RecipeUser.user_id == user_id, RecipeUser.category_id == category_id)
            .order_by(self.model.id)
        )
        return await fetch_all(self.session, statement)

    async def get_recipes(self, recipe_ids: list[int]) -> list[Recipe]:
        """Вернуть рецепты по списку id."""
        if not recipe_ids:
            return []
        statement = select(self.model).where(self.model.id.in_(recipe_ids))
        return await fetch_all(self.session, statement)

    async def get_public_recipes_by_category(
        self,
        category_id: int,
        *,
        exclude_user_id: int | None = None,
    ) -> list[Recipe]:
        """Вернуть публичные рецепты с видео в категории, по одному на видео (последний рецепт)."""
        video_key = func.coalesce(func.nullif(Video.original_url, ""), func.nullif(Video.video_url, ""))
        filters = [
            RecipeUser.category_id == int(category_id),
            video_key.is_not(None),
        ]
        if exclude_user_id is not None:
            filters.append(
                self.model.id.notin_(select(RecipeUser.recipe_id).where(RecipeUser.user_id == int(exclude_user_id)))
            )

        latest_by_video_subq = (
            select(func.max(self.model.id).label("recipe_id"))
            .join(RecipeUser, RecipeUser.recipe_id == self.model.id)
            .join(Video, Video.recipe_id == self.model.id)
            .where(*filters)
            .group_by(video_key)
            .subquery()
        )

        statement = (
            select(self.model)
            .join(latest_by_video_subq, latest_by_video_subq.c.recipe_id == self.model.id)
            .order_by(self.model.id.desc())
        )
        return await fetch_all(self.session, statement)

    async def search_recipes_by_title(self, user_id: int, query: str) -> list[Recipe]:
        """Найти рецепты пользователя по подстроке в названии (ilike)."""
        pattern = f"%{query}%"
        statement = (
            select(self.model)
            .join(RecipeUser, RecipeUser.recipe_id == self.model.id)
            .where(RecipeUser.user_id == user_id, self.model.title.ilike(pattern))
            .order_by(self.model.id)
        )
        return await fetch_all(self.session, statement)

    async def search_recipes_by_ingredient(self, user_id: int, query: str) -> list[Recipe]:
        """Найти рецепты пользователя по подстроке в названии ингредиента (ilike)."""
        pattern = f"%{query}%"
        statement = (
            select(self.model)
            .join(RecipeUser, RecipeUser.recipe_id == self.model.id)
            .join(RecipeIngredient, RecipeIngredient.recipe_id == self.model.id)
            .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
            .where(RecipeUser.user_id == user_id, Ingredient.name.ilike(pattern))
            .distinct()
            .order_by(self.model.id)
        )
        return await fetch_all(self.session, statement)

    async def get_name_by_id(self, recipe_id: int) -> str | None:
        """Вернуть название рецепта по id."""
        statement = select(self.model.title).where(self.model.id == recipe_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_category_id_by_recipe_id(self, recipe_id: int, user_id: int) -> int | None:
        """Вернуть category_id связи пользователя с рецептом."""
        statement = select(RecipeUser.category_id).where(
            RecipeUser.recipe_id == recipe_id,
            RecipeUser.user_id == user_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    # ── Admin panel ───────────────────────────────────────────────────────────

    async def list_page(self, *, offset: int, limit: int, q: str) -> tuple[list[Recipe], int]:
        """Вернуть страницу рецептов и общее количество для admin-панели."""
        base = select(self.model)
        if q:
            base = base.where(self.model.title.ilike(f"%{q}%"))
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = (
            base.options(
                joinedload(self.model.ingredients),
                joinedload(self.model.linked_users),
                joinedload(self.model.video),
            )
            .order_by(desc(self.model.id))
            .offset(offset)
            .limit(limit)
        )
        recipes = (await self.session.execute(stmt)).unique().scalars().all()
        return list(recipes), int(total)

    async def get_for_admin(self, recipe_id: int) -> Recipe | None:
        """Загрузить рецепт со всеми связями для admin-панели."""
        stmt = (
            select(self.model)
            .where(self.model.id == recipe_id)
            .options(
                joinedload(self.model.ingredient_links).joinedload(RecipeIngredient.ingredient),
                joinedload(self.model.linked_users),
                joinedload(self.model.video),
                joinedload(self.model.recipe_users).joinedload(RecipeUser.category),
            )
        )
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def get_legacy_ingredient_recipe_ids(self, recipe_ids: list[int]) -> set[int]:
        """Из переданных id вернуть те, у кого есть ингредиент без quantity (старый формат)."""
        if not recipe_ids:
            return set()
        stmt = (
            select(RecipeIngredient.recipe_id)
            .where(RecipeIngredient.recipe_id.in_(recipe_ids), RecipeIngredient.quantity.is_(None))
            .distinct()
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return set(rows)

    def _ingredient_links_option(self):
        return joinedload(self.model.ingredient_links).joinedload(RecipeIngredient.ingredient)

    async def get_needing_qty_backfill(self, limit: int | None) -> list[Recipe]:
        """Рецепты с хотя бы одним ингредиентом без quantity, с загруженными связями."""
        subq = (
            select(RecipeIngredient.recipe_id).where(RecipeIngredient.quantity.is_(None)).distinct().scalar_subquery()
        )
        stmt = (
            select(self.model)
            .where(self.model.id.in_(subq))
            .options(self._ingredient_links_option())
            .order_by(self.model.id)
        )
        if limit:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).unique().scalars().all())

    async def get_needing_qty_backfill_one(self, recipe_id: int) -> Recipe | None:
        """Загрузить один рецепт с ingredient_links для бэкфилла."""
        stmt = select(self.model).where(self.model.id == recipe_id).options(self._ingredient_links_option())
        return (await self.session.execute(stmt)).unique().scalar_one_or_none()

    async def update_meta(self, recipe_id: int, *, title: str, description: str | None) -> Recipe | None:
        """Обновить название и описание рецепта. Вернуть обновлённый объект."""
        return await self.update_fields(recipe_id, {"title": title, "description": description})
