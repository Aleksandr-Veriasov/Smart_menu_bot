from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import (
    IngredientRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    RecipeUserRepository,
    VideoRepository,
)


def _to_name(x: object) -> str:
    if isinstance(x, dict):
        return (x.get("name") or "").strip()
    # если у тебя другой формат, добавь ветки
    return str(x or "").strip()


async def save_recipe_draft_service(
    session: AsyncSession,
    *,
    title: str,
    description: str | None,
    ingredients_raw: Iterable[object],
    video_url: str | None = None,
    original_url: str | None = None,
) -> int:
    """
    Сохраняет рецепт без привязки к пользователю и категории.
    Используется до выбора категории пользователем.
    """
    recipe = await RecipeRepository.create_basic(
        session,
        title=title,
        description=description or "Не указано",
    )

    try:
        names = [n for n in map(_to_name, ingredients_raw) if n]
        id_by_name = await IngredientRepository.bulk_get_or_create(session, names)
        await RecipeIngredientRepository.bulk_link(session, int(recipe.id), id_by_name.values())

        if video_url:
            await VideoRepository.create(session, video_url, int(recipe.id), original_url=original_url)

        await session.commit()
        return int(recipe.id)
    except Exception:
        await session.rollback()
        raise


async def link_recipe_to_user_service(
    session: AsyncSession,
    *,
    recipe_id: int,
    user_id: int,
    category_id: int,
) -> None:
    """Привязывает рецепт к пользователю и категории."""
    await RecipeUserRepository.link_user(session, recipe_id, user_id, category_id)
    await session.commit()
