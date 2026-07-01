import json
import logging
import re
import time
from decimal import Decimal

from packages.db.models import Ingredient, Recipe, RecipeIngredient
from packages.db.repository.ingredient import IngredientRepository
from packages.db.repository.recipe import RecipeRepository
from packages.db.repository.recipe_ingredient import RecipeIngredientRepository
from packages.recipes_core.deepseek_parsers import IngredientItem
from packages.recipes_core.promts import (
    SYSTEM_PROMPT_BACKFILL,
    SYSTEM_PROMPT_BACKFILL_PARTIAL,
)
from packages.recipes_core.services.provider import get_default_extractor
from packages.recipes_core.units import normalize_unit
from packages.schemas.ingredient import DupGroup
from packages.schemas.recipe import IngredientLink
from packages.services.base import BaseService
from packages.utils import normalize_quantity

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

    async def count_pending_backfill(self, fmt: str | None = None) -> int:
        """Количество рецептов, требующих обработки backfill (с учётом фильтра формата)."""
        async with self.db.session() as session:
            return await self.recipe_repo(session).count_needing_backfill(fmt)

    async def format_stats(self) -> dict[str, int]:
        """Статистика рецептов по статусу формата: {'old', 'partial', 'new'}."""
        async with self.db.session() as session:
            return await self.recipe_repo(session).count_by_fill_status()

    async def run_backfill(self, limit: int, dry_run: bool, fmt: str | None = None) -> dict:
        """Обогатить qty/unit ингредиентов через LLM. Вернуть {total, enriched, failed, dry_run, limit, fmt}."""
        async with self.db.session() as session:
            recipes = await self.recipe_repo(session).get_needing_qty_backfill(limit, fmt)

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
                ok = await self._enrich_recipe(recipe_fresh, session, dry_run=dry_run, fmt=fmt)
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
        return {
            "total": total,
            "enriched": enriched,
            "failed": failed,
            "dry_run": dry_run,
            "limit": limit,
            "fmt": fmt or "all",
        }

    async def enrich_one(self, recipe_id: int, *, dry_run: bool = False) -> bool:
        """Прогнать backfill для одного рецепта (заполнить qty/unit + нормализовать имена)."""
        async with self.db.session() as session:
            recipe = await self.recipe_repo(session).get_needing_qty_backfill_one(recipe_id)
            if recipe is None:
                return False
            return await self._enrich_recipe(recipe, session, dry_run=dry_run)

    async def _enrich_recipe(self, recipe: Recipe, session, *, dry_run: bool, fmt: str | None = None) -> bool:
        """Обогатить рецепт через LLM: заполнить qty/unit и нормализовать имена ингредиентов."""
        links = recipe.ingredient_links
        if not links:
            return True

        is_partial = fmt == "partial"
        system_prompt = SYSTEM_PROMPT_BACKFILL_PARTIAL if is_partial else SYSTEM_PROMPT_BACKFILL
        extractor = get_default_extractor()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._build_backfill_message(recipe, links, include_known=is_partial)},
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

        matches = self._match_items_to_links(links, items)

        # Чистое имя, которое хотим для каждой связи (имя из ответа ИИ либо regex-фолбэк).
        desired_names = [self._desired_name(matched, link.ingredient.name) for link, matched in matches]
        id_by_name: dict[str, int] = {}
        if not dry_run:
            id_by_name = await self.ingredient_repo(session).bulk_get_or_create([n for n in desired_names if n])

        new_links: list[IngredientLink] = []
        obsolete_ids: list[int] = []
        enriched = 0
        renamed = 0
        for (link, matched), new_name in zip(matches, desired_names, strict=False):
            target_id = link.ingredient_id
            if new_name and new_name != link.ingredient.name:
                renamed += 1
                target_id = id_by_name.get(new_name, link.ingredient_id)
                if target_id != link.ingredient_id:
                    obsolete_ids.append(link.ingredient_id)

            quantity, unit = link.quantity, link.unit
            if matched is not None and (matched.quantity is not None or matched.unit is not None):
                quantity, unit = matched.quantity, matched.unit
                enriched += 1

            new_links.append(IngredientLink(ingredient_id=target_id, quantity=quantity, unit=unit))

        logger.info(
            "Recipe %d (%s): enriched=%d renamed=%d /%d%s",
            recipe.id,
            recipe.title[:40],
            enriched,
            renamed,
            len(links),
            " [DRY RUN]" if dry_run else "",
        )

        if not dry_run:
            await self.recipe_ingredient_repo(session).bulk_link(int(recipe.id), new_links)
            for old_id in obsolete_ids:
                await self.recipe_ingredient_repo(session).delete_link(int(recipe.id), old_id)
            await self.ingredient_repo(session).delete_orphans(obsolete_ids)

        return True

    @classmethod
    def _desired_name(cls, matched: IngredientItem | None, current: str) -> str:
        """Чистое имя ингредиента: из ответа ИИ (нормализованное), иначе regex-фолбэк от текущего."""
        raw = matched.name if (matched is not None and matched.name) else current
        return cls._canonical_name(cls._clean_ingredient_name(raw))

    @staticmethod
    def _canonical_name(name: str) -> str:
        """Свести к единому виду: схлопнуть пробелы и сделать первую букву заглавной."""
        name = re.sub(r"\s+", " ", name or "").strip()
        return name[:1].upper() + name[1:] if name else name

    @staticmethod
    def _clean_ingredient_name(name: str) -> str:
        """Очистить имя: убрать скобки с количеством и лишние пробелы, сохранив регистр."""
        return re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", name)).strip()

    @classmethod
    def _norm_name(cls, name: str) -> str:
        """Нормализовать имя для сопоставления: очистить от скобок и привести к нижнему регистру."""
        return cls._clean_ingredient_name(name).lower()

    @classmethod
    def _match_items_to_links(
        cls, links: list[RecipeIngredient], items: list[IngredientItem]
    ) -> list[tuple[RecipeIngredient, IngredientItem | None]]:
        """Сопоставить ответ LLM со связями рецепта.

        ИИ нормализует имена, поэтому матчить его новые имена со «грязными» именами в БД
        ненадёжно. Основной путь — позиционный: промпт требует тот же порядок и количество.
        При расхождении количества — best-effort по точному нормализованному имени.
        """
        if len(items) == len(links):
            return list(zip(links, items, strict=False))

        logger.warning(
            "Backfill: LLM вернул %d позиций вместо %d — фолбэк на сопоставление по имени",
            len(items),
            len(links),
        )
        item_by_norm: dict[str, IngredientItem] = {}
        for item in items:
            item_by_norm.setdefault(cls._norm_name(item.name), item)
        return [(link, item_by_norm.get(cls._norm_name(link.ingredient.name))) for link in links]

    @classmethod
    def _build_backfill_message(
        cls, recipe: Recipe, links: list[RecipeIngredient], *, include_known: bool = False
    ) -> str:
        if include_known:
            numbered = "\n".join(
                f"{i}. {link.ingredient.name} — {cls._format_known_qty(link)}" for i, link in enumerate(links, 1)
            )
        else:
            numbered = "\n".join(f"{i}. {link.ingredient.name}" for i, link in enumerate(links, 1))
        return "\n".join(
            [
                f"Рецепт: {recipe.title}",
                f"Описание: {recipe.description or 'не указано'}",
                f"Ингредиенты ({len(links)} шт — верни ровно столько же объектов в том же порядке):",
                numbered,
            ]
        )

    @staticmethod
    def _format_known_qty(link: RecipeIngredient) -> str:
        """Известные qty/unit связи для промпта partial-бэкфилла, либо метка «нужно оценить»."""
        if link.quantity is None and link.unit is None:
            return "количество неизвестно, оцени"
        qty = format(link.quantity.normalize(), "f") if link.quantity is not None else "?"
        unit = link.unit or ""
        return f"известно: {qty} {unit}".strip()

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
                    quantity = normalize_quantity(Decimal(str(raw_qty)))
                except Exception:
                    pass
            items.append(IngredientItem(name=name, quantity=quantity, unit=normalize_unit(entry.get("unit"))))
        return items
