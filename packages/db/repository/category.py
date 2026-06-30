from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from packages.db.models import Category, RecipeUser
from packages.db.schemas import CategoryCreate

from .base import BaseRepository


class CategoryRepository(BaseRepository[Category]):
    """Репозиторий для работы с категориями рецептов."""

    model = Category

    async def create(self, payload: CategoryCreate) -> Category:
        """Создать категорию. Raises ValueError при дублировании slug."""
        data = payload.model_dump(exclude_unset=True)
        category = self.model(**data)
        self.session.add(category)
        try:
            return await self.save(category)
        except IntegrityError as exc:
            raise ValueError("Category already exists") from exc

    async def get_by_slug(self, slug: str) -> Category | None:
        """Найти категорию по slug."""
        statement = select(self.model).where(self.model.slug == slug)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_all(self) -> list[Category]:
        """Вернуть все категории, отсортированные по id."""
        statement = select(self.model).order_by(self.model.id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def count_recipes_by_category(self) -> dict[int, int]:
        """Количество уникальных рецептов в каждой категории: {category_id: count}."""
        statement = select(
            RecipeUser.category_id,
            func.count(func.distinct(RecipeUser.recipe_id)),
        ).group_by(RecipeUser.category_id)
        result = await self.session.execute(statement)
        return {category_id: count for category_id, count in result.all()}

    async def get_by_user_id(self, user_id: int) -> list[Category]:
        """Вернуть категории, в которых у пользователя есть хотя бы один рецепт."""
        statement = (
            select(self.model)
            .join(RecipeUser, RecipeUser.category_id == self.model.id)
            .where(RecipeUser.user_id == user_id)
            .group_by(self.model.id)
            .order_by(self.model.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
