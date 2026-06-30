import asyncio
from dataclasses import dataclass
from html import escape as html_escape

import requests
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common_settings.settings import settings
from packages.db.models import Recipe
from packages.db.repository import (
    CategoryRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    RecipeUserRepository,
    VideoRepository,
)
from packages.db.schemas import RecipeUpdate
from packages.recipes_core.ingredients_parser import parse_ingredients_lines
from packages.redis.repository import (
    CategoryCacheRepository,
    RecipeActionCacheRepository,
    RecipeCacheRepository,
    UserMessageIdsCacheRepository,
    WebAppRecipeDraftCacheRepository,
)
from packages.schemas.webapp import (
    WebAppCategoryRead,
    WebAppRecipeDraft,
    WebAppRecipePatch,
    WebAppRecipeRead,
)
from packages.services.base import BaseService
from packages.utils import format_qty_unit


@dataclass
class PatchResult:
    recipe_id: int
    title_changed: bool
    category_changed: bool
    membership_changed: bool
    old_category_id: int
    new_category_id: int


class WebAppService(BaseService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.category_cache = CategoryCacheRepository(self.redis)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def list_categories(self, user_id: int) -> list[WebAppCategoryRead]:
        """Вернуть список категорий (из кеша Redis, при необходимости с догрузкой из БД)."""
        cached = await self.category_cache.get_all_categories()
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
        try:
            await self.category_cache.set_all_categories(rows)
        except Exception:
            pass

        return [WebAppCategoryRead(id=c.id, name=c.name, slug=c.slug) for c in categories]

    async def get_recipe(self, recipe_id: int, user_id: int) -> WebAppRecipeRead:
        """Вернуть рецепт пользователя для редактирования в WebApp."""
        async with self.db.session() as session:
            recipe, category_id = await self._load_recipe_for_user(session, recipe_id=recipe_id, user_id=user_id)
            return WebAppRecipeRead.from_recipe(recipe, category_id=category_id)

    async def get_recipe_draft(self, recipe_id: int, user_id: int) -> WebAppRecipeDraft:
        """Прочитать короткоживущий черновик навигации для рецепта."""
        async with self.db.session() as session:
            await self._load_recipe_for_user(session, recipe_id=recipe_id, user_id=user_id)

        data = await WebAppRecipeDraftCacheRepository(self.redis).get(user_id=user_id, recipe_id=recipe_id) or {}
        return WebAppRecipeDraft(title=data.get("title"), category_id=data.get("category_id"))

    async def set_recipe_draft(self, recipe_id: int, user_id: int, payload: WebAppRecipeDraft) -> WebAppRecipeDraft:
        """Сохранить/обновить короткоживущий черновик навигации."""
        async with self.db.session() as session:
            await self._load_recipe_for_user(session, recipe_id=recipe_id, user_id=user_id)

        draft_cache = WebAppRecipeDraftCacheRepository(self.redis)
        await draft_cache.set_merge(
            user_id=user_id,
            recipe_id=recipe_id,
            title=payload.title,
            category_id=payload.category_id,
        )
        data = await draft_cache.get(user_id=user_id, recipe_id=recipe_id) or {}
        return WebAppRecipeDraft(title=data.get("title"), category_id=data.get("category_id"))

    async def delete_recipe_draft(self, recipe_id: int, user_id: int) -> None:
        """Удалить черновик навигации."""
        await WebAppRecipeDraftCacheRepository(self.redis).clear(user_id=user_id, recipe_id=recipe_id)

    async def patch_recipe(self, recipe_id: int, user_id: int, payload: WebAppRecipePatch) -> WebAppRecipeRead:
        """Обновить поля рецепта. При необходимости клонирует общий рецепт."""
        path_recipe_id = recipe_id

        async with self.db.session() as session:
            result = await self._apply_patch(session, recipe_id=recipe_id, user_id=user_id, payload=payload)
            recipe, category_id = await self._load_recipe_for_user(session, recipe_id=result.recipe_id, user_id=user_id)
            read = WebAppRecipeRead.from_recipe(recipe, category_id=category_id)

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
        return read

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _load_recipe_for_user(self, session: AsyncSession, *, recipe_id: int, user_id: int) -> tuple[Recipe, int]:
        row = await RecipeRepository(session).get_with_category_for_user(recipe_id, user_id)
        if row is None:
            raise LookupError("Рецепт не найден")
        return row

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

        is_shared = await RecipeUserRepository(session).count_by_recipe(int(recipe.id)) >= 2

        title_will_change = payload.title is not None and payload.title != (recipe.title or "")
        description_will_change = payload.description is not None and payload.description != recipe.description
        ingredients_will_change = False
        if payload.ingredients is not None:
            ingredients_will_change = True  # структурированный список всегда перезаписываем
        elif payload.ingredients_text is not None:
            ingredients_will_change = parse_ingredients_lines(payload.ingredients_text) != [
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
                title_changed = True
                await RecipeRepository(session).update_title(int(recipe_id), payload.title)

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
                ri_repo = RecipeIngredientRepository(session)
                await ri_repo.delete_all_by_recipe(int(recipe_id))
                await ri_repo.save_from_names(int(recipe_id), parse_ingredients_lines(payload.ingredients_text))

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
        new_title = payload.title if payload.title is not None else str(original.title)
        new_description = payload.description if payload.description is not None else original.description
        new_category_id = int(payload.category_id) if payload.category_id is not None else int(category_id)
        category_changed = new_category_id != int(category_id)

        new_recipe = await RecipeRepository(session).create_basic(new_title, new_description)

        if getattr(original, "video", None) is not None:
            await VideoRepository(session).create(
                str(original.video.video_url),
                int(new_recipe.id),
                original_url=original.video.original_url,
            )

        ri_repo = RecipeIngredientRepository(session)
        if payload.ingredients is not None:
            await ri_repo.save_from_structured(int(new_recipe.id), payload.ingredients)
        elif payload.ingredients_text is not None:
            await ri_repo.save_from_names(int(new_recipe.id), parse_ingredients_lines(payload.ingredients_text))
        else:
            names = [str(i.name) for i in (original.ingredients or []) if getattr(i, "name", None)]
            await ri_repo.save_from_names(int(new_recipe.id), names)

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
        try:
            if title_changed or category_changed or membership_changed:
                recipe_cache = RecipeCacheRepository(self.redis)
                for cid in {int(old_category_id), int(new_category_id)}:
                    await recipe_cache.invalidate_all_recipes_ids_and_titles(int(user_id), cid)
            if category_changed or membership_changed:
                await self.category_cache.invalidate_user_categories(int(user_id))
            await WebAppRecipeDraftCacheRepository(self.redis).clear(
                user_id=int(user_id), recipe_id=int(draft_recipe_id_to_clear)
            )
        except Exception:
            pass

    async def _update_telegram_message(self, *, user_id: int, recipe: Recipe) -> None:
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
        ingredients_text = "\n".join(
            (
                f"- {html_escape(link.ingredient.name or '')} — {qty}"
                if (qty := format_qty_unit(link.quantity, link.unit))
                else f"- {html_escape(link.ingredient.name or '')}"
            )
            for link in (recipe.ingredient_links or [])
        )
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
