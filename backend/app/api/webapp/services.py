"""
Сервисный слой Telegram WebApp.

Содержит низкоуровневые операции:
- чтение данных из БД для WebApp
- работу с Redis (инвалидация кешей, чистка черновиков WebApp)

Бизнес-логика и сценарии находятся в `backend.app.api.webapp.workflows`.
"""

import sqlalchemy as sa
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.app.utils.fastapi_state import get_backend_redis_optional
from packages.db.models import Category, Recipe, RecipeUser
from packages.redis.repository import (
    CategoryCacheRepository,
    RecipeCacheRepository,
    WebAppRecipeDraftCacheRepository,
)


async def load_recipe_for_user(session: AsyncSession, *, recipe_id: int, user_id: int) -> tuple[Recipe, int]:
    """
    Загрузить рецепт + category_id пользователя для этого рецепта.

    Если рецепт не связан с пользователем, вернёт HTTP 404.
    """

    stmt = (
        select(Recipe, RecipeUser.category_id)
        .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
        .where(Recipe.id == int(recipe_id), RecipeUser.user_id == int(user_id))
        .options(joinedload(Recipe.ingredients), joinedload(Recipe.video))
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Рецепт не найден")
    recipe: Recipe = row[0]
    category_id: int = int(row[1])
    return recipe, category_id


async def count_recipe_users(session: AsyncSession, *, recipe_id: int) -> int:
    """Сколько пользователей связано с рецептом через `recipe_users`."""

    stmt = select(sa.func.count(RecipeUser.id)).where(RecipeUser.recipe_id == int(recipe_id))
    return int((await session.execute(stmt)).scalar_one() or 0)


async def invalidate_bot_caches_best_effort(
    request: Request,
    *,
    user_id: int,
    old_category_id: int,
    new_category_id: int,
    title_changed: bool,
    category_changed: bool,
    membership_changed: bool,
    draft_recipe_id_to_clear: int,
) -> None:
    """Инвалидировать кеши в Redis (для бота); ошибки игнорируются (по возможности)."""

    redis = get_backend_redis_optional(request)
    if redis is None:
        return
    try:
        if title_changed or category_changed or membership_changed:
            for cid in {int(old_category_id), int(new_category_id)}:
                await RecipeCacheRepository.invalidate_all_recipes_ids_and_titles(redis, int(user_id), int(cid))
        if category_changed or membership_changed:
            await CategoryCacheRepository.invalidate_user_categories(redis, int(user_id))
        await WebAppRecipeDraftCacheRepository.clear(
            redis,
            user_id=int(user_id),
            recipe_id=int(draft_recipe_id_to_clear),
        )
    except Exception:
        pass


async def list_user_categories(session: AsyncSession, *, user_id: int) -> list[tuple[int, str, str | None]]:
    """Список категорий, в которых у пользователя есть хотя бы один рецепт (id, name, slug)."""

    stmt = (
        select(Category.id, Category.name, Category.slug)
        .join(RecipeUser, RecipeUser.category_id == Category.id)
        .where(RecipeUser.user_id == int(user_id))
        .group_by(Category.id, Category.name, Category.slug)
        .order_by(Category.id)
    )
    rows = (await session.execute(stmt)).all()
    return [(int(r.id), str(r.name), r.slug) for r in rows]
