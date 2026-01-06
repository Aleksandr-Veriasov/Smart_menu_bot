from __future__ import annotations

import logging
from typing import Any, ClassVar

from markupsafe import Markup, escape
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from packages.db.database import Database
from packages.db.models import Admin as AdminModel
from packages.db.models import Category, Ingredient, Recipe, User, Video
from packages.redis.redis_conn import get_redis
from packages.redis.repository import CategoryCacheRepository
from packages.security.passwords import verify_password

logger = logging.getLogger(__name__)


class AdminAuth(AuthenticationBackend):
    def __init__(self, db: Database, secret_key: str = "admin-auth") -> None:
        super().__init__(secret_key)
        self.db = db

    async def login(self, request: Request) -> bool:
        try:
            form = await request.form()
            username = str(form.get("username") or "").strip() if isinstance(form.get("username"), str) else ""
            logger.debug(f"📼 username = {username}")

            password = str(form.get("password") or "").strip() if isinstance(form.get("password"), str) else ""
            if not username or not password:
                return False

            async with self.db.session() as session:  # AsyncSession
                admin = await self._get_admin(session, username)
                logger.debug(f"📼 admin = {admin}")

            if not admin:
                return False

            if verify_password(password, str(admin.password_hash)):
                # помечаем сессию как вошедшую
                request.session["admin_login"] = admin.login
                return True

            return False
        except Exception as e:
            # важный лог — увидишь реальную причину 500 в консоли
            logging.getLogger(__name__).exception("AdminAuth.login failed: %s", e)
            return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return "admin_login" in request.session

    async def _get_admin(self, session: AsyncSession, login: str) -> AdminModel | None:
        res = await session.execute(select(AdminModel).where(AdminModel.login == login))
        return res.scalar_one_or_none()


class UserAdmin(ModelView, model=User):  # type: ignore[call-arg]
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"

    column_list = [
        "id",
        "username",
        "first_name",
        "last_name",
        "created_at",
        "recipes_count",
    ]
    column_labels = {
        "id": "ID",
        "username": "Логин",
        "first_name": "Имя",
        "last_name": "Фамилия",
        "created_at": "Создан",
        "recipes_count": "Рецептов",
        "recipes_name": "Рецепты",
    }
    column_sortable_list = ["id", "username", "created_at"]
    column_searchable_list = ["id", "username", "first_name", "last_name"]

    column_details_list = [
        "id",
        "username",
        "first_name",
        "last_name",
        "created_at",
        "recipes_name",
    ]

    form_columns = ["username", "first_name", "last_name"]

    can_create = True
    can_edit = True
    can_delete = False

    column_formatters = {
        "recipes_count": lambda m, _: len(m.recipes or []),
    }

    column_formatters_detail: ClassVar[Any] = {
        "recipes_name": lambda m, _: (
            Markup("<br>".join(escape(r.title) for r in (m.recipes or []))) if m.recipes else "—"
        ),
    }


class CategoryAdmin(ModelView, model=Category):  # type: ignore[call-arg]
    name = "Категория"
    name_plural = "Категории"
    icon = "fa-solid fa-folder"

    column_list = ["id", "name", "slug", "recipes_count"]
    column_details_list = ["id", "name", "slug"]

    column_labels = {
        "id": "ID",
        "name": "Название",
        "slug": "Слаг",
        "recipes_count": "Кол-во рецептов",
    }
    column_sortable_list = ["id", "name", "slug"]
    column_searchable_list = ["name", "slug"]

    form_columns = ["name", "slug"]

    can_create = True
    can_edit = True
    can_delete = True

    column_formatters = {
        "recipes_count": lambda m, _: len(m.recipes or []),
    }

    async def on_model_change(
        self,
        data: dict,
        model: Category,
        is_created: bool,
        request: Request,
    ) -> None:
        """
        Вызывается ПЕРЕД созданием/обновлением.
        Сохраним старый slug, чтобы after_model_change мог сравнить.
        """
        if not is_created:
            # model.slug на этом этапе — старое значение
            request.state._old_slug = model.slug
            logger.debug(f"Old slug saved: {request.state._old_slug}")

    async def after_model_change(
        self,
        data: dict,
        model: Category,
        is_created: bool,
        request: Request,
    ) -> None:
        """
        Вызывается после создания/обновления.
        • Если slug менялся — инвалидируем старый ключ.
        • Всегда пересоздаём ключ для актуального slug.
        """
        # достаём Redis из твоего AppState
        redis = await get_redis()
        if not redis:
            logger.warning("Redis is not available via get_redis()")
            return

        old_slug = getattr(request.state, "_old_slug", None)
        new_slug = model.slug
        logger.debug(f"New slug: {new_slug}")

        # если это апдейт и slug поменялся — сносим старый ключ
        if not is_created and old_slug and old_slug != new_slug:
            await CategoryCacheRepository.invalidate_by_slug(redis, old_slug)

        # на всякий случай удалим и текущий ключ
        await CategoryCacheRepository.invalidate_by_slug(redis, str(new_slug))
        await CategoryCacheRepository.set_id_name_by_slug(redis, str(new_slug), model.id, model.name)

    async def after_model_delete(self, model: Category, request: Request) -> None:
        """
        При удалении категории — чистим ключ по slug.
        """
        redis = await get_redis()
        if not redis:
            logger.warning("Redis is not available via get_redis()")
            return
        await CategoryCacheRepository.invalidate_by_slug(redis, str(model.slug))


# ---------- Ingredient ----------
class IngredientAdmin(ModelView, model=Ingredient):  # type: ignore[call-arg]
    name = "Ингредиент"
    name_plural = "Ингредиенты"
    icon = "fa-solid fa-seedling"
    page_size: ClassVar[int] = 20

    column_list = ["id", "name", "recipes_count"]
    column_details_list = ["id", "name", "recipes_name"]
    column_labels = {
        "id": "ID",
        "name": "Название",
        "recipes_count": "В рецептах",
        "recipes_name": "Рецепты",
    }
    column_sortable_list = ["id", "name"]
    column_searchable_list = ["name"]

    form_columns = ["name"]

    can_create = True
    can_edit = True
    can_delete = True

    column_formatters: ClassVar[Any] = {
        "recipes_count": lambda m, _: len(m.recipes or []),
    }

    column_formatters_detail: ClassVar[Any] = {
        "recipes_name": lambda m, _: (
            Markup("<br>".join(escape(r.title) for r in (m.recipes or []))) if m.recipes else "—"
        ),
    }


# ---------- Video ----------
class VideoAdmin(ModelView, model=Video):  # type: ignore[call-arg]
    name = "Видео"
    name_plural = "Видео"
    icon = "fa-solid fa-video"

    column_list = ["id", "recipe_title", "video_url"]
    column_details_list = ["id", "recipe_title", "video_url"]
    column_labels = {
        "id": "ID",
        "recipe_title": "Рецепт",
        "video_url": "Ссылка",
    }
    column_sortable_list = ["id"]
    column_searchable_list = ["video_url"]

    form_columns = ["recipe", "video_url"]

    can_create = True
    can_edit = True
    can_delete = True

    column_formatters: ClassVar[Any] = {
        "recipe_title": lambda m, _: (m.recipe.title if m.recipe else "—"),
        "video_url": lambda m, _: (m.video_url if m.video_url else "—"),
    }

    column_formatters_detail: ClassVar[Any] = {
        "recipe_title": lambda m, _: (m.recipe.title if m.recipe else "—"),
        "video_url": lambda m, _: (m.video_url if m.video_url else "—"),
    }

    # выпадающий поиск по рецептам
    form_ajax_refs = {
        "recipe": {"fields": ("title",)},
    }


# ---------- Recipe ----------
class RecipeAdmin(ModelView, model=Recipe):  # type: ignore[call-arg]
    name = "Рецепт"
    name_plural = "Рецепты"
    icon = "fa-solid fa-bowl-food"
    page_size: ClassVar[int] = 20

    column_list = [
        "id",
        "title",
        "category_name",
        "user_username",
        "ingredients_count",
        "has_video",
        "created_at",
    ]
    column_labels = {
        "id": "ID",
        "title": "Название",
        "category_name": "Категория",
        "user_username": "Пользователь",
        "ingredients_count": "Ингр., шт.",
        "has_video": "Видео",
        "created_at": "Создан",
        "ingredients_text": "Ингредиенты",
        "video_link": "Видео",
    }
    column_sortable_list = ["id", "title", "created_at"]
    column_searchable_list = ["title"]

    column_details_list = [
        "id",
        "title",
        "description",
        "ingredients_text",
        "category_name",
        "user_username",
        "video_link",
        "created_at",
    ]

    form_columns = [
        "title",
        "description",
        "user",
        "category",
        "ingredients",
        "video",
    ]

    can_create = True
    can_edit = True
    can_delete = False

    column_formatters: ClassVar[Any] = {
        "category_name": lambda m, _: (m.category.name if m.category else "—"),
        "user_username": lambda m, _: ((m.user.username or f"ID {m.user.id}") if m.user else "—"),
        "ingredients_count": lambda m, _: len(m.ingredients or []),
        "has_video": lambda m, _: "✓" if getattr(m, "video", None) else "—",
    }

    column_formatters_detail: ClassVar[Any] = {
        "category_name": lambda m, _: (m.category.name if m.category else "—"),
        "user_username": lambda m, _: ((m.user.username or f"ID {m.user.id}") if m.user else "—"),
        "ingredients_text": lambda m, _: (
            Markup("<br>".join(escape(i.name) for i in (m.ingredients or []))) if m.ingredients else "—"
        ),
        "video_link": lambda m, _: (m.video.video_url if m.video and m.video.video_url else "—"),
        # опционально: многострочный текст без HTML
        "description": lambda m, _: (Markup("<br>".join(escape(m.description).splitlines())) if m.description else "—"),
    }

    # ajax-подгрузка полей в формах
    form_ajax_refs = {
        "user": {"fields": ("username", "first_name", "last_name")},
        "category": {"fields": ("name", "slug")},
        "ingredients": {"fields": ("name",), "page_size": 20},
    }


class AdminUserAdmin(ModelView, model=AdminModel):  # type: ignore[call-arg]
    name = "Админ"
    name_plural = "Админы"
    icon = "fa-solid fa-user"


def setup_admin(admin: Admin) -> None:
    """Регистрируем все ModelView в SQLAdmin."""
    admin.add_view(UserAdmin)
    admin.add_view(RecipeAdmin)
    admin.add_view(CategoryAdmin)
    admin.add_view(VideoAdmin)
    admin.add_view(IngredientAdmin)
    # admin.add_view(AdminUserAdmin)
