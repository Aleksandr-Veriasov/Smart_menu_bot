import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.db.models import RecipeUser

from .base import BaseRepository


class RecipeUserRepository(BaseRepository[RecipeUser]):
    """Репозиторий для связей рецепт-пользователь."""

    model = RecipeUser

    async def link_user(self, recipe_id: int, user_id: int, category_id: int) -> None:
        """Привязать пользователя к рецепту в категории. Дубликат игнорируется."""
        stmt = (
            pg_insert(self.model)
            .values({"recipe_id": int(recipe_id), "user_id": int(user_id), "category_id": int(category_id)})
            .on_conflict_do_nothing(index_elements=[self.model.recipe_id, self.model.user_id])
        )
        await self.session.execute(stmt)

    async def upsert_user_link(self, recipe_id: int, user_id: int, category_id: int) -> bool:
        """
        Создаёт связь рецепт-пользователь или обновляет category_id для существующей.
        Возвращает True, если связь была создана, иначе False.
        """
        stmt = (
            pg_insert(self.model)
            .values({"recipe_id": int(recipe_id), "user_id": int(user_id), "category_id": int(category_id)})
            .on_conflict_do_update(
                index_elements=[self.model.recipe_id, self.model.user_id],
                set_={"category_id": int(category_id)},
            )
            .returning(sa.literal_column("xmax = 0"))
        )
        result = await self.session.execute(stmt)
        return bool(result.scalar_one())

    async def unlink_user(self, recipe_id: int, user_id: int) -> None:
        """Удалить связь пользователя с рецептом."""
        statement = sa.delete(self.model).where(
            self.model.recipe_id == recipe_id,
            self.model.user_id == user_id,
        )
        await self.session.execute(statement)

    async def is_linked(self, recipe_id: int, user_id: int) -> bool:
        """Проверить, привязан ли пользователь к рецепту."""
        statement = select(func.count(self.model.id)).where(
            self.model.recipe_id == recipe_id,
            self.model.user_id == user_id,
        )
        result = await self.session.execute(statement)
        return (result.scalar_one_or_none() or 0) > 0

    async def get_any_category_id(self, recipe_id: int) -> int | None:
        """Вернуть category_id любого пользователя, привязанного к рецепту."""
        statement = select(self.model.category_id).where(self.model.recipe_id == recipe_id).limit(1)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()
