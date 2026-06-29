"""admin: служебные инструменты (бэкфилл, дедупликация ингредиентов)."""

import asyncio
import sys
from dataclasses import dataclass

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select, update

from backend.app.admin.deps import check_auth, current_login
from backend.app.admin.templates import templates
from backend.app.utils.fastapi_state import get_backend_db
from packages.db.models import RecipeIngredient
from packages.db.models.recipe import Ingredient

router = APIRouter()

_MAX_LIMIT = 100


# ── Дедупликация ингредиентов ──────────────────────────────────────────────────


@dataclass
class DupGroup:
    lower_name: str
    variants: list[tuple[int, str, int]]  # (id, name, recipe_count)


async def _find_dup_groups(session) -> list[DupGroup]:
    """Возвращает группы ингредиентов с одинаковым LOWER(name)."""
    rows = (
        await session.execute(
            select(
                func.lower(Ingredient.name).label("lower_name"),
                func.count(Ingredient.id).label("cnt"),
            )
            .group_by(func.lower(Ingredient.name))
            .having(func.count(Ingredient.id) > 1)
            .order_by(func.lower(Ingredient.name))
        )
    ).all()

    if not rows:
        return []

    lower_names = [r.lower_name for r in rows]
    variants_rows = (
        await session.execute(
            select(
                Ingredient.id,
                Ingredient.name,
                func.count(RecipeIngredient.recipe_id).label("recipe_count"),
            )
            .outerjoin(RecipeIngredient, RecipeIngredient.ingredient_id == Ingredient.id)
            .where(func.lower(Ingredient.name).in_(lower_names))
            .group_by(Ingredient.id, Ingredient.name)
            .order_by(func.lower(Ingredient.name), func.count(RecipeIngredient.recipe_id).desc())
        )
    ).all()

    groups: dict[str, list[tuple[int, str, int]]] = {}
    for row in variants_rows:
        key = row.name.lower()
        groups.setdefault(key, []).append((row.id, row.name, row.recipe_count))

    return [DupGroup(lower_name=k, variants=v) for k, v in groups.items()]


@router.get("/tools/dedup", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_page(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        groups = await _find_dup_groups(session)

    return templates.TemplateResponse(
        request,
        "tools/dedup.html",
        {
            "admin_login": current_login(request),
            "groups": groups,
            "merged": None,
        },
    )


@router.post("/tools/dedup/merge", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def dedup_merge(
    request: Request,
    canonical_id: int = Form(...),
    duplicate_id: int = Form(...),
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        # Обновляем recipe_ingredients: заменяем duplicate → canonical.
        # ON CONFLICT: если запись (recipe_id, canonical_id) уже есть — удаляем дубль.
        dup_recipe_ids = (
            (
                await session.execute(
                    select(RecipeIngredient.recipe_id).where(RecipeIngredient.ingredient_id == duplicate_id)
                )
            )
            .scalars()
            .all()
        )

        existing_canonical = set(
            (
                await session.execute(
                    select(RecipeIngredient.recipe_id).where(RecipeIngredient.ingredient_id == canonical_id)
                )
            )
            .scalars()
            .all()
        )

        # Строки где canonical уже есть → просто удаляем дубль
        conflict_recipe_ids = [rid for rid in dup_recipe_ids if rid in existing_canonical]
        # Строки где canonical нет → переставляем ingredient_id
        remap_recipe_ids = [rid for rid in dup_recipe_ids if rid not in existing_canonical]

        if remap_recipe_ids:
            await session.execute(
                update(RecipeIngredient)
                .where(
                    RecipeIngredient.ingredient_id == duplicate_id,
                    RecipeIngredient.recipe_id.in_(remap_recipe_ids),
                )
                .values(ingredient_id=canonical_id)
            )

        # Удаляем конфликтующие строки дубля
        await session.execute(delete(RecipeIngredient).where(RecipeIngredient.ingredient_id == duplicate_id))

        # Удаляем сам ингредиент-дубль
        dup_ingredient = await session.get(Ingredient, duplicate_id)
        dup_name = dup_ingredient.name if dup_ingredient else str(duplicate_id)
        canonical_ingredient = await session.get(Ingredient, canonical_id)
        canonical_name = canonical_ingredient.name if canonical_ingredient else str(canonical_id)

        if dup_ingredient:
            await session.delete(dup_ingredient)

        merged_info = {
            "canonical_id": canonical_id,
            "canonical_name": canonical_name,
            "dup_name": dup_name,
            "remapped": len(remap_recipe_ids),
            "dropped": len(conflict_recipe_ids),
        }

    async with db.session() as session:
        groups = await _find_dup_groups(session)

    return templates.TemplateResponse(
        request,
        "tools/dedup.html",
        {
            "admin_login": current_login(request),
            "groups": groups,
            "merged": merged_info,
        },
    )


@router.get("/tools/backfill", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def backfill_page(request: Request) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    db = get_backend_db(request)
    async with db.session() as session:
        pending_count: int = (
            await session.execute(
                select(func.count(func.distinct(RecipeIngredient.recipe_id))).where(RecipeIngredient.quantity.is_(None))
            )
        ).scalar_one()

    return templates.TemplateResponse(
        request,
        "tools/backfill.html",
        {
            "admin_login": current_login(request),
            "pending_count": pending_count,
            "result": None,
        },
    )


@router.post("/tools/backfill", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def backfill_run(
    request: Request,
    dry_run: bool = Form(False),
    limit: int = Form(10),
) -> HTMLResponse | RedirectResponse:
    if redirect := check_auth(request):
        return redirect

    limit = max(1, min(limit, _MAX_LIMIT))

    cmd = [sys.executable, "scripts/backfill_ingredient_qty.py", "--limit", str(limit)]
    if dry_run:
        cmd.append("--dry-run")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        output = stdout.decode("utf-8", errors="replace")
        success = proc.returncode == 0
    except TimeoutError:
        output = "Превышен таймаут (120 с)"
        success = False
    except Exception as exc:
        output = f"Ошибка запуска: {exc}"
        success = False

    db = get_backend_db(request)
    async with db.session() as session:
        pending_count: int = (
            await session.execute(
                select(func.count(func.distinct(RecipeIngredient.recipe_id))).where(RecipeIngredient.quantity.is_(None))
            )
        ).scalar_one()

    return templates.TemplateResponse(
        request,
        "tools/backfill.html",
        {
            "admin_login": current_login(request),
            "pending_count": pending_count,
            "result": {"output": output, "success": success, "dry_run": dry_run, "limit": limit},
        },
    )
