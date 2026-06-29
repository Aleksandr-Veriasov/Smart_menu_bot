"""Бэкфилл quantity/unit для существующих рецептов через LLM.

Запуск:
    python scripts/backfill_ingredient_qty.py            # боевой режим
    python scripts/backfill_ingredient_qty.py --dry-run  # только логирование
    python scripts/backfill_ingredient_qty.py --limit 10 # первые N рецептов

Скрипт берёт рецепты где хотя бы один ингредиент без quantity,
делает один LLM-запрос на рецепт и обновляет qty/unit в junction-таблице.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path

# Добавляем корень проекта в sys.path чтобы импорты пакетов работали
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from packages.db.database import Database
from packages.db.models import Recipe, RecipeIngredient
from packages.db.repository.recipe_ingredient import (
    IngredientLink,
    RecipeIngredientRepository,
)
from packages.recipes_core.deepseek_parsers import (
    IngredientItem,
)
from packages.recipes_core.promts import SYSTEM_PROMPT_BACKFILL
from packages.recipes_core.services.provider import get_default_extractor
from packages.recipes_core.units import normalize_unit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Минимальная пауза между LLM-запросами (rate-limit ~2 req/s)
_REQUEST_INTERVAL = 0.5


def _build_user_message(recipe: Recipe, ingredient_names: list[str]) -> str:
    lines = [
        f"Рецепт: {recipe.title}",
        f"Описание: {recipe.description or 'не указано'}",
        "Ингредиенты: " + ", ".join(ingredient_names),
    ]
    return "\n".join(lines)


def _parse_backfill_response(raw: str, ingredient_names: list[str]) -> list[IngredientItem]:
    """Парсит JSON-массив из ответа LLM; фолбэк — пустой список."""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        logger.warning("LLM вернул невалидный JSON: %.120s", raw)
        return []

    if not isinstance(data, list):
        logger.warning("LLM вернул не массив: %s", type(data))
        return []

    items: list[IngredientItem] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "").strip()
        if not name:
            continue

        raw_qty = entry.get("quantity")
        quantity: Decimal | None = None
        if raw_qty is not None:
            try:
                quantity = Decimal(str(raw_qty))
            except Exception:
                pass

        unit = normalize_unit(entry.get("unit"))
        items.append(IngredientItem(name=name, quantity=quantity, unit=unit))

    return items


async def _get_recipes_needing_backfill(session: AsyncSession, limit: int | None) -> list[Recipe]:
    """Возвращает рецепты где хотя бы один ингредиент без quantity."""
    subq = select(RecipeIngredient.recipe_id).where(RecipeIngredient.quantity.is_(None)).distinct().scalar_subquery()
    stmt = (
        select(Recipe)
        .where(Recipe.id.in_(subq))
        .options(joinedload(Recipe.ingredient_links).joinedload(RecipeIngredient.ingredient))
        .order_by(Recipe.id)
    )
    if limit:
        stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return list(result.unique().scalars().all())


async def _enrich_recipe(
    recipe: Recipe,
    session: AsyncSession,
    *,
    dry_run: bool,
) -> bool:
    """Обогащает один рецепт через LLM. Возвращает True при успехе."""
    links_without_qty = [link for link in recipe.ingredient_links if link.quantity is None]
    if not links_without_qty:
        return True

    ingredient_names = [link.ingredient.name for link in recipe.ingredient_links]
    extractor = get_default_extractor()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_BACKFILL},
        {"role": "user", "content": _build_user_message(recipe, ingredient_names)},
    ]

    try:
        raw = extractor.chat.chat(messages, temperature=0.0, timeout=30.0)
    except Exception as exc:
        logger.error("Recipe %d: LLM ошибка: %s", recipe.id, exc)
        return False

    items = _parse_backfill_response(raw, ingredient_names)
    if not items:
        logger.warning("Recipe %d: пустой результат от LLM", recipe.id)
        return False

    name_to_item = {item.name: item for item in items}

    updated_links: list[IngredientLink] = []
    for link in recipe.ingredient_links:
        matched = name_to_item.get(link.ingredient.name)
        if matched and (matched.quantity is not None or matched.unit is not None):
            updated_links.append(
                IngredientLink(
                    ingredient_id=link.ingredient_id,
                    quantity=matched.quantity,
                    unit=matched.unit,
                )
            )

    enriched_count = len(updated_links)
    logger.info(
        "Recipe %d (%s): enriched=%d/%d%s",
        recipe.id,
        recipe.title[:40],
        enriched_count,
        len(ingredient_names),
        " [DRY RUN]" if dry_run else "",
    )

    if dry_run:
        for link in updated_links:
            logger.debug("  ingredient_id=%d qty=%s unit=%s", link.ingredient_id, link.quantity, link.unit)
        return True

    if updated_links:
        await RecipeIngredientRepository(session).bulk_link(int(recipe.id), updated_links)
        await session.commit()

    return True


async def run(*, dry_run: bool, limit: int | None) -> None:
    db = Database()
    async with db.session() as session:
        recipes = await _get_recipes_needing_backfill(session, limit)

    total = len(recipes)
    logger.info("Найдено рецептов для бэкфилла: %d%s", total, f" (limit={limit})" if limit else "")

    if total == 0:
        logger.info("Всё уже заполнено, выходим.")
        return

    enriched = 0
    failed = 0
    t_start = time.monotonic()

    for i, recipe in enumerate(recipes):
        if i > 0:
            time.sleep(_REQUEST_INTERVAL)

        async with db.session() as session:
            # Перезагружаем рецепт в новой сессии с нужными связями
            stmt = (
                select(Recipe)
                .where(Recipe.id == recipe.id)
                .options(joinedload(Recipe.ingredient_links).joinedload(RecipeIngredient.ingredient))
            )
            result = await session.execute(stmt)
            recipe_fresh = result.unique().scalar_one()

            ok = await _enrich_recipe(recipe_fresh, session, dry_run=dry_run)
            if ok:
                enriched += 1
            else:
                failed += 1

    elapsed = time.monotonic() - t_start
    logger.info(
        "Готово за %.1fs: enriched=%d / total=%d / failed=%d%s",
        elapsed,
        enriched,
        total,
        failed,
        " [DRY RUN]" if dry_run else "",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill ingredient qty/unit via LLM")
    parser.add_argument("--dry-run", action="store_true", help="Не писать в БД, только логировать")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число рецептов")
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
