import asyncio
from dataclasses import dataclass
from html import escape as html_escape

import requests
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from packages.common_settings.settings import settings
from packages.db.database import Database
from packages.db.models import Recipe, RecipeIngredient, RecipeUser, Video
from packages.db.repository import (
    CategoryRepository,
    IngredientRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    RecipeUserRepository,
)
from packages.db.schemas import RecipeUpdate
from packages.redis.keys import RedisKeys
from packages.redis.repository import (
    CategoryCacheRepository,
    RecipeActionCacheRepository,
    RecipeCacheRepository,
    UserMessageIdsCacheRepository,
    WebAppRecipeDraftCacheRepository,
)
from packages.schemas.webapp import (
    IngredientItemRead,
    IngredientItemWrite,
    WebAppCategoryRead,
    WebAppRecipeDraft,
    WebAppRecipePatch,
    WebAppRecipeRead,
)


@dataclass
class PatchResult:
    recipe_id: int
    title_changed: bool
    category_changed: bool
    membership_changed: bool
    old_category_id: int
    new_category_id: int


class WebAppService:
    def __init__(self, db: Database, redis: Redis | None) -> None:
        self.db = db
        self.redis = redis
        self.keys = RedisKeys

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def list_categories(self, user_id: int) -> list[WebAppCategoryRead]:
        """Вернуть список категорий (из кеша Redis, при необходимости с догрузкой из БД)."""
        if self.redis is not None:
            cache = CategoryCacheRepository(self.redis)
            cached = await cache.get_all_name_and_slug()
            if cached and all((isinstance((cid := x.get("id")), int) and cid > 0) for x in cached):
                out: list[WebAppCategoryRead] = []
                for x in cached:
                    try:
                        out.append(
                            WebAppCategoryRead(
                                id=int(x["id"]),
                                name=str(x.get("name") or ""),
                                slug=(str(x.get("slug")) if x.get("slug") is not None else None),
                            )
                        )
                    except Exception:
                        continue
                if out:
                    return out

        async with self.db.session() as session:
            categories = await CategoryRepository(session).get_all()

        rows = [{"id": c.id, "name": c.name, "slug": c.slug} for c in categories]
        if self.redis is not None:
            try:
                await CategoryCacheRepository(self.redis).set_all_name_and_slug(rows)
            except Exception:
                pass

        return [WebAppCategoryRead(id=c.id, name=c.name, slug=c.slug) for c in categories]

    async def get_recipe(self, recipe_id: int, user_id: int) -> WebAppRecipeRead:
        """Вернуть рецепт пользователя для редактирования в WebApp."""
        async with self.db.session() as session:
            recipe, category_id = await self._load_recipe_for_user(session, recipe_id=recipe_id, user_id=user_id)
            return self._to_read(recipe, category_id=category_id)

    async def get_recipe_draft(self, recipe_id: int, user_id: int) -> WebAppRecipeDraft:
        """Прочитать короткоживущий черновик навигации для рецепта."""
        async with self.db.session() as session:
            await self._load_recipe_for_user(session, recipe_id=recipe_id, user_id=user_id)

        data: dict = {}
        if self.redis is not None:
            data = await WebAppRecipeDraftCacheRepository(self.redis).get(user_id=user_id, recipe_id=recipe_id) or {}
        return WebAppRecipeDraft(title=data.get("title"), category_id=data.get("category_id"))

    async def set_recipe_draft(self, recipe_id: int, user_id: int, payload: WebAppRecipeDraft) -> WebAppRecipeDraft:
        """Сохранить/обновить короткоживущий черновик навигации."""
        async with self.db.session() as session:
            await self._load_recipe_for_user(session, recipe_id=recipe_id, user_id=user_id)

        data: dict = {}
        if self.redis is not None:
            await WebAppRecipeDraftCacheRepository(self.redis).set_merge(
                user_id=user_id,
                recipe_id=recipe_id,
                title=payload.title,
                category_id=payload.category_id,
            )
            data = await WebAppRecipeDraftCacheRepository(self.redis).get(user_id=user_id, recipe_id=recipe_id) or {}
        return WebAppRecipeDraft(title=data.get("title"), category_id=data.get("category_id"))

    async def delete_recipe_draft(self, recipe_id: int, user_id: int) -> None:
        """Удалить черновик навигации."""
        if self.redis is not None:
            await WebAppRecipeDraftCacheRepository(self.redis).clear(user_id=user_id, recipe_id=recipe_id)

    async def patch_recipe(self, recipe_id: int, user_id: int, payload: WebAppRecipePatch) -> WebAppRecipeRead:
        """Обновить поля рецепта. При необходимости клонирует общий рецепт."""
        path_recipe_id = recipe_id

        async with self.db.session() as session:
            result = await self._apply_patch(session, recipe_id=recipe_id, user_id=user_id, payload=payload)
            recipe, category_id = await self._load_recipe_for_user(session, recipe_id=result.recipe_id, user_id=user_id)

        await self._invalidate_caches(
            user_id=user_id,
            old_category_id=result.old_category_id,
            new_category_id=result.new_category_id,
            title_changed=result.title_changed,
            category_changed=result.category_changed,
            membership_changed=result.membership_changed,
            draft_recipe_id_to_clear=path_recipe_id,
        )
        await self._update_telegram_message(user_id=user_id, recipe=recipe)
        return self._to_read(recipe, category_id=category_id)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _load_recipe_for_user(self, session: AsyncSession, *, recipe_id: int, user_id: int) -> tuple[Recipe, int]:
        stmt = (
            select(Recipe, RecipeUser.category_id)
            .join(RecipeUser, RecipeUser.recipe_id == Recipe.id)
            .where(Recipe.id == int(recipe_id), RecipeUser.user_id == int(user_id))
            .options(joinedload(Recipe.ingredients), joinedload(Recipe.video))
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            raise LookupError("Рецепт не найден")
        return row[0], int(row[1])

    async def _count_recipe_users(self, session: AsyncSession, *, recipe_id: int) -> int:
        stmt = select(sa.func.count(RecipeUser.id)).where(RecipeUser.recipe_id == int(recipe_id))
        return int((await session.execute(stmt)).scalar_one() or 0)

    async def _apply_patch(
        self,
        session: AsyncSession,
        *,
        recipe_id: int,
        user_id: int,
        payload: WebAppRecipePatch,
    ) -> PatchResult:
        recipe, category_id = await self._load_recipe_for_user(session, recipe_id=recipe_id, user_id=user_id)
        old_category_id = int(category_id)

        is_shared = await self._count_recipe_users(session, recipe_id=int(recipe.id)) >= 2

        title_will_change = payload.title is not None and self._validate_title(payload.title) != (recipe.title or "")
        description_will_change = payload.description is not None and payload.description != recipe.description
        ingredients_will_change = False
        if payload.ingredients is not None:
            ingredients_will_change = True  # структурированный список всегда перезаписываем
        elif payload.ingredients_text is not None:
            ingredients_will_change = self._parse_ingredients(payload.ingredients_text) != [
                str(i.name) for i in (recipe.ingredients or []) if getattr(i, "name", None)
            ]

        title_changed = category_changed = membership_changed = False

        if is_shared and (title_will_change or description_will_change or ingredients_will_change):
            new_recipe_id, category_changed = await self._clone_recipe(
                session, original=recipe, user_id=user_id, category_id=old_category_id, payload=payload
            )
            membership_changed = True
            recipe_id = new_recipe_id
        else:
            if payload.title is not None and title_will_change:
                title = self._validate_title(payload.title)
                title_changed = True
                await RecipeRepository(session).update_title(int(recipe_id), title)

            if payload.description is not None and description_will_change:
                await RecipeRepository(session).update(int(recipe_id), RecipeUpdate(description=payload.description))

            if payload.category_id is not None:
                requested = int(payload.category_id)
                category_changed = requested != old_category_id
                if category_changed:
                    await RecipeRepository(session).update_category(
                        recipe_id=int(recipe_id), user_id=int(user_id), category_id=requested
                    )
                    category_id = requested

            if payload.ingredients_text is not None and ingredients_will_change:
                await session.execute(sa.delete(RecipeIngredient).where(RecipeIngredient.recipe_id == int(recipe_id)))
                await self._save_ingredients(session, int(recipe_id), payload)

        _, new_category_id = await self._load_recipe_for_user(session, recipe_id=int(recipe_id), user_id=user_id)
        return PatchResult(
            recipe_id=int(recipe_id),
            title_changed=title_changed,
            category_changed=category_changed,
            membership_changed=membership_changed,
            old_category_id=old_category_id,
            new_category_id=int(new_category_id),
        )

    async def _clone_recipe(
        self,
        session: AsyncSession,
        *,
        original: Recipe,
        user_id: int,
        category_id: int,
        payload: WebAppRecipePatch,
    ) -> tuple[int, bool]:
        new_title = self._validate_title(payload.title) if payload.title is not None else str(original.title)
        new_description = payload.description if payload.description is not None else original.description
        new_category_id = int(payload.category_id) if payload.category_id is not None else int(category_id)
        category_changed = new_category_id != int(category_id)

        new_recipe = await RecipeRepository(session).create_basic(new_title, new_description)

        if getattr(original, "video", None) is not None:
            session.add(
                Video(
                    recipe_id=int(new_recipe.id),
                    video_url=str(original.video.video_url),
                    original_url=original.video.original_url,
                )
            )

        if payload.ingredients_text is not None or payload.ingredients is not None:
            await self._save_ingredients(session, int(new_recipe.id), payload)
        else:
            names = [str(i.name) for i in (original.ingredients or []) if getattr(i, "name", None)]
            if names:
                id_by_name = await IngredientRepository(session).bulk_get_or_create(names)
                await RecipeIngredientRepository(session).bulk_link_ids(int(new_recipe.id), id_by_name.values())

        await RecipeUserRepository(session).link_user(int(new_recipe.id), int(user_id), int(new_category_id))
        await RecipeUserRepository(session).unlink_user(int(original.id), int(user_id))

        return int(new_recipe.id), category_changed

    async def _invalidate_caches(
        self,
        *,
        user_id: int,
        old_category_id: int,
        new_category_id: int,
        title_changed: bool,
        category_changed: bool,
        membership_changed: bool,
        draft_recipe_id_to_clear: int,
    ) -> None:
        if self.redis is None:
            return
        try:
            if title_changed or category_changed or membership_changed:
                recipe_cache = RecipeCacheRepository(self.redis)
                for cid in {int(old_category_id), int(new_category_id)}:
                    await recipe_cache.invalidate_all_recipes_ids_and_titles(int(user_id), cid)
            if category_changed or membership_changed:
                await CategoryCacheRepository(self.redis).invalidate_user_categories(int(user_id))
            await WebAppRecipeDraftCacheRepository(self.redis).clear(
                user_id=int(user_id), recipe_id=int(draft_recipe_id_to_clear)
            )
        except Exception:
            pass

    async def _update_telegram_message(self, *, user_id: int, recipe: Recipe) -> None:
        if self.redis is None:
            return

        cached = await UserMessageIdsCacheRepository(self.redis).get_user_message_ids(int(user_id))
        if not cached or not cached.message_ids:
            return
        target_message_id = int(cached.message_ids[-1])

        recipes_state = await RecipeActionCacheRepository(self.redis).get(int(user_id), "recipes_state") or {}
        try:
            page = int(recipes_state.get("recipes_page", 0))
        except Exception:
            page = 0
        category_slug = str(recipes_state.get("category_slug") or "recipes")
        mode = str(recipes_state.get("mode") or "show")
        if mode not in {"show", "edit", "search"}:
            mode = "show"

        base = settings.fast_api.base_url()
        webapp_url = f"{base}/webapp/edit-recipe.html?recipe_id={int(recipe.id)}"
        reply_markup = {
            "inline_keyboard": [
                [{"text": "✏️ Редактировать рецепт", "web_app": {"url": webapp_url}}],
                [{"text": "🗑 Удалить рецепт", "callback_data": f"recipe:delete:{int(recipe.id)}"}],
                [{"text": "⏪ Назад", "callback_data": f"page:{page}:{category_slug}:{mode}"}],
                [{"text": "🏠 На главную", "callback_data": "nav:start"}],
            ]
        }

        safe_title = html_escape(recipe.title or "")
        safe_description = html_escape(recipe.description or "")
        ingredients_text = "\n".join(f"- {html_escape(i.name or '')}" for i in (recipe.ingredients or []))
        text = (
            "✅ Рецепт обновлен.\n\n"
            f"🍽 <b>Название рецепта:</b> {safe_title}\n\n"
            f"📝 <b>Рецепт:</b>\n{safe_description}\n\n"
            f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
        )

        token = settings.telegram.bot_token.get_secret_value().strip()
        if not token:
            return
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            "chat_id": cached.chat_id,
            "message_id": target_message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        }

        def _call() -> None:
            try:
                requests.post(url, json=payload, timeout=7).raise_for_status()
            except Exception:
                pass

        await asyncio.to_thread(_call)

    # ------------------------------------------------------------------ #
    # Static utilities                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_title(raw: str) -> str:
        title = (raw or "").strip()
        if not title:
            raise ValueError("Название не может быть пустым")
        return title

    @staticmethod
    async def _save_ingredients(
        session: AsyncSession,
        recipe_id: int,
        payload: WebAppRecipePatch,
    ) -> None:
        """Сохраняет ингредиенты из payload. Structured-список имеет приоритет над text."""
        from packages.schemas.recipe import IngredientLink

        if payload.ingredients is not None:
            items: list[IngredientItemWrite] = payload.ingredients
            names = [item.name for item in items if item.name]
            if not names:
                return
            id_by_name = await IngredientRepository(session).bulk_get_or_create(names)
            links = [
                IngredientLink(
                    ingredient_id=id_by_name[item.name],
                    quantity=item.quantity,
                    unit=item.unit,
                )
                for item in items
                if item.name and item.name in id_by_name
            ]
            await RecipeIngredientRepository(session).bulk_link(recipe_id, links)
        elif payload.ingredients_text is not None:
            names = WebAppService._parse_ingredients(payload.ingredients_text)
            if not names:
                return
            id_by_name = await IngredientRepository(session).bulk_get_or_create(names)
            await RecipeIngredientRepository(session).bulk_link_ids(recipe_id, id_by_name.values())

    @staticmethod
    def _parse_ingredients(text: str) -> list[str]:
        raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        parts: list[str] = []
        for line in raw.split("\n"):
            line = line.strip()
            if line:
                parts.append(line)
        return list(dict.fromkeys(parts))

    @staticmethod
    def _to_read(recipe: Recipe, *, category_id: int) -> WebAppRecipeRead:
        ingredients = [str(i.name) for i in (recipe.ingredients or []) if getattr(i, "name", None)]
        ingredient_details = [
            IngredientItemRead(
                name=str(link.ingredient.name),
                quantity=link.quantity,
                unit=link.unit,
            )
            for link in getattr(recipe, "ingredient_links", [])
            if getattr(link, "ingredient", None) and link.ingredient.name
        ]
        return WebAppRecipeRead(
            id=int(recipe.id),
            title=str(recipe.title),
            description=recipe.description,
            category_id=int(category_id),
            ingredients=ingredients,
            ingredient_details=ingredient_details,
        )
