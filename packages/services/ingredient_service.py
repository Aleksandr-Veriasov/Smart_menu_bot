import json
import logging
import time
from decimal import Decimal

from packages.db.models import Ingredient, Recipe
from packages.db.repository.ingredient import IngredientRepository
from packages.db.repository.recipe import RecipeRepository
from packages.db.repository.recipe_ingredient import RecipeIngredientRepository
from packages.recipes_core.deepseek_parsers import IngredientItem
from packages.recipes_core.promts import SYSTEM_PROMPT_BACKFILL
from packages.recipes_core.services.provider import get_default_extractor
from packages.recipes_core.units import normalize_unit
from packages.schemas.ingredient import DupGroup
from packages.schemas.recipe import IngredientLink
from packages.services.base import BaseService

logger = logging.getLogger(__name__)

_BACKFILL_REQUEST_INTERVAL = 0.5


class IngredientService(BaseService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ingredient_repo = IngredientRepository
        self.recipe_ingredient_repo = RecipeIngredientRepository
        self.recipe_repo = RecipeRepository

    async def list_page(self, page: int, page_size: int, q: str = "") -> tuple[list[Ingredient], int]:
        """Вернуть страницу ингредиентов и общее количество для admin-панели."""
        async with self.db.session() as session:
            return await self.ingredient_repo(session).list_page(offset=(page - 1) * page_size, limit=page_size, q=q)

    async def get_or_raise(self, ing_id: int) -> Ingredient:
        """Вернуть ингредиент или бросить LookupError."""
        async with self.db.session() as session:
            ing = await self.ingredient_repo(session).get_by_id(ing_id)
        if ing is None:
            raise LookupError(f"Ингредиент #{ing_id} не найден")
        return ing

    async def create(self, name: str) -> None:
        """Создать ингредиент. Raises ValueError если уже существует."""
        async with self.db.session() as session:
            await self.ingredient_repo(session).create(name)

    async def update(self, ing_id: int, name: str) -> Ingredient:
        """Переименовать ингредиент. Raises LookupError если не найден, ValueError если имя занято."""
        async with self.db.session() as session:
            repo = self.ingredient_repo(session)
            ing = await repo.get_by_id(ing_id)
            if ing is None:
                raise LookupError(f"Ингредиент #{ing_id} не найден")
            if await repo.get_by_name_excluding(name, ing_id):
                raise ValueError(f"Ингредиент «{name}» уже существует")
            ing.name = name
            return await repo.save(ing)

    async def delete(self, ing_id: int) -> None:
        """Удалить ингредиент (если найден)."""
        async with self.db.session() as session:
            ing = await self.ingredient_repo(session).get_by_id(ing_id)
            if ing:
                await session.delete(ing)

    # ── Admin tools ───────────────────────────────────────────────────────────

    async def find_dup_groups(self) -> list[DupGroup]:
        """Вернуть группы ингредиентов с одинаковым LOWER(name)."""
        async with self.db.session() as session:
            return await self.ingredient_repo(session).find_dup_groups()

    async def merge_duplicate(self, canonical_id: int, duplicate_id: int) -> dict:
        """Смержить дубль в canonical: перевесить RecipeIngredient, удалить дубль."""
        async with self.db.session() as session:
            return await self.ingredient_repo(session).merge_duplicate(canonical_id, duplicate_id)

    async def count_pending_backfill(self) -> int:
        """Количество рецептов с хотя бы одним ингредиентом без quantity."""
        async with self.db.session() as session:
            return await self.recipe_ingredient_repo(session).count_pending_backfill()

    async def run_backfill(self, limit: int, dry_run: bool) -> dict:
        """Обогатить qty/unit ингредиентов через LLM. Вернуть {total, enriched, failed, dry_run, limit}."""
        async with self.db.session() as session:
            recipes = await self.recipe_repo(session).get_needing_qty_backfill(limit)

        total = len(recipes)
        enriched = 0
        failed = 0
        t_start = time.monotonic()

        for i, recipe in enumerate(recipes):
            if i > 0:
                time.sleep(_BACKFILL_REQUEST_INTERVAL)
            async with self.db.session() as session:
                recipe_fresh = await self.recipe_repo(session).get_needing_qty_backfill_one(recipe.id)
                if recipe_fresh is None:
                    failed += 1
                    continue
                ok = await self._enrich_recipe(recipe_fresh, session, dry_run=dry_run)
            if ok:
                enriched += 1
            else:
                failed += 1

        elapsed = time.monotonic() - t_start
        logger.info(
            "Backfill готово за %.1fs: enriched=%d / total=%d / failed=%d%s",
            elapsed,
            enriched,
            total,
            failed,
            " [DRY RUN]" if dry_run else "",
        )
        return {"total": total, "enriched": enriched, "failed": failed, "dry_run": dry_run, "limit": limit}

    async def _enrich_recipe(self, recipe: Recipe, session, *, dry_run: bool) -> bool:
        """Обогатить один рецепт через LLM. Вернуть True при успехе."""
        links_without_qty = [link for link in recipe.ingredient_links if link.quantity is None]
        if not links_without_qty:
            return True

        ingredient_names = [link.ingredient.name for link in recipe.ingredient_links]
        extractor = get_default_extractor()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_BACKFILL},
            {"role": "user", "content": self._build_backfill_message(recipe, ingredient_names)},
        ]

        try:
            raw = extractor.chat.chat(messages, temperature=0.0, timeout=30.0)
        except Exception as exc:
            logger.error("Recipe %d: LLM ошибка: %s", recipe.id, exc)
            return False

        items = self._parse_backfill_response(raw)
        if not items:
            logger.warning("Recipe %d: пустой результат от LLM", recipe.id)
            return False

        name_to_item = {item.name: item for item in items}
        updated_links = [
            IngredientLink(
                ingredient_id=link.ingredient_id,
                quantity=matched.quantity,
                unit=matched.unit,
            )
            for link in recipe.ingredient_links
            if (matched := name_to_item.get(link.ingredient.name))
            and (matched.quantity is not None or matched.unit is not None)
        ]

        logger.info(
            "Recipe %d (%s): enriched=%d/%d%s",
            recipe.id,
            recipe.title[:40],
            len(updated_links),
            len(ingredient_names),
            " [DRY RUN]" if dry_run else "",
        )

        if not dry_run and updated_links:
            await self.recipe_ingredient_repo(session).bulk_link(int(recipe.id), updated_links)
            await session.commit()

        return True

    @staticmethod
    def _build_backfill_message(recipe: Recipe, ingredient_names: list[str]) -> str:
        return "\n".join(
            [
                f"Рецепт: {recipe.title}",
                f"Описание: {recipe.description or 'не указано'}",
                "Ингредиенты: " + ", ".join(ingredient_names),
            ]
        )

    @staticmethod
    def _parse_backfill_response(raw: str) -> list[IngredientItem]:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning("LLM вернул невалидный JSON: %.120s", raw)
            return []
        if not isinstance(data, list):
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
            items.append(IngredientItem(name=name, quantity=quantity, unit=normalize_unit(entry.get("unit"))))
        return items
