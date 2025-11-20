from typing import Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.repository import (
    IngredientRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    VideoRepository,
)
from packages.db.schemas import RecipeCreate


def _to_name(x: object) -> str:
    if isinstance(x, dict):
        return (x.get("name") or "").strip()
    # если у тебя другой формат, добавь ветки
    return str(x or "").strip()


async def save_recipe_service(
    session: AsyncSession,
    *,
    user_id: int,
    title: str,
    description: str | None,
    category_id: int,
    ingredients_raw: Iterable[object],
    video_url: str | None = None,
) -> Optional[int]:
    """
    Сохраняет рецепт:
    1) создаёт Recipe
    2) bulk get_or_create ингредиенты
    3) bulk связки рецепт-ингредиент
    4) опционально видео
    Коммит — здесь; репозитории коммит не делают.
    """
    if not (user_id and category_id):
        return None

    recipe = await RecipeRepository.create(
        session,
        RecipeCreate(
            user_id=user_id,
            title=title,
            description=description or "Не указано",
            category_id=int(category_id),
        ),
    )

    try:
        names = [n for n in map(_to_name, ingredients_raw) if n]
        id_by_name = await IngredientRepository.bulk_get_or_create(
            session, names
        )
        await RecipeIngredientRepository.bulk_link(
            session, int(recipe.id), id_by_name.values()
        )

        if video_url:
            await VideoRepository.create(session, video_url, int(recipe.id))

        await session.commit()
        return int(recipe.id)
    except Exception:
        await session.rollback()
        raise
