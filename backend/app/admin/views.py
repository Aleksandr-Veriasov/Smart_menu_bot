import logging
from typing import Any, ClassVar

from markupsafe import Markup, escape
from sqladmin import Admin, BaseView, ModelView, expose
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.app.utils.fastapi_state import get_backend_redis
from packages.db.database import Database
from packages.db.models import Admin as AdminModel
from packages.db.models import (
    BroadcastCampaign,
    BroadcastMessage,
    Category,
    Ingredient,
    Recipe,
    User,
    Video,
)
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
        "linked_recipes_count",
    ]
    column_labels = {
        "id": "ID",
        "username": "Логин",
        "first_name": "Имя",
        "last_name": "Фамилия",
        "created_at": "Создан",
        "linked_recipes_count": "Доступных рецептов",
        "linked_recipes_name": "Доступные рецепты",
    }
    column_sortable_list = ["id", "username", "created_at"]
    column_searchable_list = ["id", "username", "first_name", "last_name"]

    column_details_list = [
        "id",
        "username",
        "first_name",
        "last_name",
        "created_at",
        "linked_recipes_name",
    ]

    form_columns = ["username", "first_name", "last_name"]

    can_create = True
    can_edit = True
    can_delete = False

    column_formatters = {
        "linked_recipes_count": lambda m, _: len(getattr(m, "linked_recipes", None) or []),
    }

    column_formatters_detail: ClassVar[Any] = {
        "linked_recipes_name": lambda m, _: (
            Markup("<br>".join(escape(r.title) for r in (getattr(m, "linked_recipes", None) or [])))
            if getattr(m, "linked_recipes", None)
            else "—"
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
        "recipes_count": lambda m, _: len(getattr(m, "recipe_users", None) or []),
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
            logger.debug(f"Старый slug сохранён: {request.state._old_slug}")

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
        # Redis берём из app.state (без создания новых подключений)
        redis = get_backend_redis(request)

        old_slug = getattr(request.state, "_old_slug", None)
        new_slug = model.slug
        logger.debug(f"Новый slug: {new_slug}")

        # если это апдейт и slug поменялся — сносим старый ключ
        if not is_created and old_slug and old_slug != new_slug:
            await CategoryCacheRepository.invalidate_by_slug(redis, old_slug)

        # на всякий случай удалим и текущий ключ
        await CategoryCacheRepository.invalidate_by_slug(redis, str(new_slug))
        await CategoryCacheRepository.set_id_name_by_slug(redis, str(new_slug), model.id, model.name)
        # список всех категорий тоже сбрасываем при создании/изменении
        await CategoryCacheRepository.invalidate_all_name_and_slug(redis)

    async def after_model_delete(self, model: Category, request: Request) -> None:
        """
        При удалении категории — чистим ключ по slug.
        """
        redis = get_backend_redis(request)
        await CategoryCacheRepository.invalidate_by_slug(redis, str(model.slug))
        await CategoryCacheRepository.invalidate_all_name_and_slug(redis)


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
            Markup("<br>".join(escape(r.title) for r in (getattr(m, "recipes", None) or [])))
            if getattr(m, "recipes", None)
            else "—"
        ),
    }


class VideoAdmin(ModelView, model=Video):  # type: ignore[call-arg]
    name = "Видео"
    name_plural = "Видео"
    icon = "fa-solid fa-video"

    column_list = ["id", "recipe_title", "video_url", "original_url"]
    column_details_list = ["id", "recipe_title", "video_url", "original_url"]
    column_labels = {
        "id": "ID",
        "recipe_title": "Рецепт",
        "video_url": "Ссылка",
        "original_url": "Оригинальная ссылка",
    }
    column_sortable_list = ["id"]
    column_searchable_list = ["video_url", "original_url"]
    column_select_related = ["recipe"]

    form_columns = ["recipe", "video_url", "original_url"]

    can_create = True
    can_edit = True
    can_delete = True

    column_formatters: ClassVar[Any] = {
        "recipe_title": lambda m, _: (
            m.recipe.title if m.recipe and m.recipe.title else (f"ID {m.recipe_id}" if m.recipe_id else "—")
        ),
        "video_url": lambda m, _: (m.video_url if m.video_url else "—"),
        "original_url": lambda m, _: (m.original_url if m.original_url else "—"),
    }

    column_formatters_detail: ClassVar[Any] = {
        "recipe_title": lambda m, _: (
            m.recipe.title if m.recipe and m.recipe.title else (f"ID {m.recipe_id}" if m.recipe_id else "—")
        ),
        "video_url": lambda m, _: (m.video_url if m.video_url else "—"),
        "original_url": lambda m, _: (m.original_url if m.original_url else "—"),
    }

    # выпадающий поиск по рецептам
    form_ajax_refs = {
        "recipe": {"fields": ("title",)},
    }


class RecipeAdmin(ModelView, model=Recipe):  # type: ignore[call-arg]
    name = "Рецепт"
    name_plural = "Рецепты"
    icon = "fa-solid fa-bowl-food"
    page_size: ClassVar[int] = 20

    column_list = [
        "id",
        "title",
        "linked_users_count",
        "categories_count",
        "ingredients_count",
        "has_video",
        "created_at",
        "last_used_at",
    ]
    column_labels = {
        "id": "ID",
        "title": "Название",
        "linked_users_count": "Пользователей с доступом",
        "categories_count": "Категорий",
        "ingredients_count": "Ингр., шт.",
        "has_video": "Видео",
        "created_at": "Создан",
        "last_used_at": "Последнее использование",
        "ingredients_text": "Ингредиенты",
        "video_link": "Видео",
        "linked_users_text": "Пользователи с доступом",
        "categories_text": "Категории",
    }
    column_sortable_list = ["id", "title", "created_at"]
    column_searchable_list = ["title"]

    column_details_list = [
        "id",
        "title",
        "description",
        "ingredients_text",
        "linked_users_text",
        "categories_text",
        "video_link",
        "created_at",
        "last_used_at",
    ]

    form_columns = [
        "title",
        "description",
        "ingredients",
        "video",
    ]

    can_create = True
    can_edit = True
    can_delete = False

    column_formatters: ClassVar[Any] = {
        "linked_users_count": lambda m, _: len(m.linked_users or []),
        "categories_count": lambda m, _: len({ru.category_id for ru in (m.recipe_users or []) if ru.category_id}),
        "ingredients_count": lambda m, _: len(m.ingredients or []),
        "has_video": lambda m, _: "✓" if getattr(m, "video", None) else "—",
    }

    column_formatters_detail: ClassVar[Any] = {
        "linked_users_text": lambda m, _: (
            Markup("<br>".join(escape(u.username or f"ID {u.id}") for u in (m.linked_users or [])))
            if m.linked_users
            else "—"
        ),
        "categories_text": lambda m, _: (
            Markup(
                "<br>".join(
                    escape(name) for name in sorted({ru.category.name for ru in (m.recipe_users or []) if ru.category})
                )
            )
            if m.recipe_users
            else "—"
        ),
        "ingredients_text": lambda m, _: (
            Markup("<br>".join(escape(i.name) for i in (m.ingredients or []))) if m.ingredients else "—"
        ),
        "video_link": lambda m, _: (m.video.video_url if m.video and m.video.video_url else "—"),
        # опционально: многострочный текст без HTML
        "description": lambda m, _: (Markup("<br>".join(escape(m.description).splitlines())) if m.description else "—"),
    }

    # ajax-подгрузка полей в формах
    form_ajax_refs = {
        "ingredients": {"fields": ("name",), "page_size": 20},
    }


class AdminUserAdmin(ModelView, model=AdminModel):  # type: ignore[call-arg]
    name = "Админ"
    name_plural = "Админы"
    icon = "fa-solid fa-user"


class BroadcastCampaignAdmin(ModelView, model=BroadcastCampaign):  # type: ignore[call-arg]
    name = "Рассылка"
    name_plural = "Рассылки"
    icon = "fa-solid fa-bullhorn"
    page_size: ClassVar[int] = 50

    column_list = [
        "id",
        "name",
        "status",
        "audience_type",
        "scheduled_at",
        "total_recipients",
        "sent_count",
        "failed_count",
        "created_at",
        "started_at",
        "finished_at",
    ]
    column_sortable_list = ["id", "status", "scheduled_at", "created_at"]
    column_searchable_list = ["id", "name", "status", "audience_type"]

    column_labels = {
        "id": "ID",
        "name": "Название",
        "status": "Статус",
        "audience_type": "Аудитория",
        "audience_params_json": "Параметры аудитории (JSON)",
        "scheduled_at": "Запланировано (UTC)",
        "text": "Текст",
        "parse_mode": "Parse mode",
        "disable_web_page_preview": "Без превью ссылок",
        "reply_markup_json": "Кнопки (reply_markup JSON)",
        "photo_file_id": "Фото file_id",
        "photo_url": "Фото URL",
        "total_recipients": "Получателей",
        "sent_count": "Отправлено",
        "failed_count": "Ошибок",
        "created_at": "Создано",
        "outbox_created_at": "Outbox создан",
        "started_at": "Старт",
        "finished_at": "Финиш",
        "last_error": "Ошибка",
    }

    form_columns = [
        "name",
        "status",
        "scheduled_at",
        "audience_type",
        "audience_params_json",
        "text",
        "parse_mode",
        "disable_web_page_preview",
        "reply_markup_json",
        "photo_file_id",
        "photo_url",
    ]

    can_create = True
    can_edit = True
    can_delete = True


class BroadcastMessageAdmin(ModelView, model=BroadcastMessage):  # type: ignore[call-arg]
    name = "Сообщение рассылки"
    name_plural = "Сообщения рассылок"
    icon = "fa-solid fa-envelope"
    page_size: ClassVar[int] = 50

    column_list = [
        "id",
        "campaign_id",
        "chat_id",
        "status",
        "attempts",
        "next_retry_at",
        "sent_at",
        "created_at",
        "last_error",
    ]
    column_sortable_list = ["id", "campaign_id", "status", "attempts", "created_at", "next_retry_at", "sent_at"]
    column_searchable_list = ["id", "campaign_id", "chat_id", "status", "last_error"]

    column_labels = {
        "id": "ID",
        "campaign_id": "Кампания",
        "chat_id": "Chat ID",
        "status": "Статус",
        "attempts": "Попыток",
        "next_retry_at": "След. попытка (UTC)",
        "sent_at": "Отправлено (UTC)",
        "created_at": "Создано",
        "last_error": "Ошибка",
    }

    can_create = False
    can_edit = False
    can_delete = True


class RedisKeysAdmin(BaseView):
    name = "Redis ключи"
    icon = "fa-solid fa-database"
    identity = "redis_keys"

    @expose("/redis-keys", methods=["GET"], identity="redis-keys")
    async def index(self, request: Request) -> HTMLResponse:
        per_page = 100
        try:
            page = int(request.query_params.get("page", "1"))
        except ValueError:
            page = 1
        page = max(1, page)

        redis = get_backend_redis(request)

        start = (page - 1) * per_page
        cursor = 0
        skipped = 0
        collected: list[bytes] = []
        has_more = False

        while True:
            cursor, keys = await redis.scan(cursor=cursor, count=per_page)
            if keys:
                if skipped < start:
                    if skipped + len(keys) <= start:
                        skipped += len(keys)
                        keys = []
                    else:
                        offset = start - skipped
                        keys = keys[offset:]
                        skipped = start
                if keys:
                    needed = per_page - len(collected)
                    if needed > 0:
                        collected.extend(keys[:needed])
                    if len(keys) > needed:
                        has_more = True
                        break
            if cursor == 0:
                break
            if len(collected) >= per_page:
                has_more = True
                break

        keys_text = [
            (k.decode("utf-8", errors="replace") if isinstance(k, (bytes | bytearray)) else str(k)) for k in collected
        ]
        keys_text.sort()
        total_keys = await redis.dbsize()
        ttls: list[int] = []
        if keys_text:
            pipe = redis.pipeline()
            for key in keys_text:
                pipe.ttl(key)
            ttls = await pipe.execute()

        def _format_ttl(raw: int | None) -> str:
            if raw is None:
                return "unknown"
            if raw == -1:
                return "no-expiry"
            if raw == -2:
                return "missing"
            minutes = raw // 60
            seconds = raw % 60
            return f"{minutes}m {seconds}s"

        rows = [{"key": key, "ttl": _format_ttl(ttl)} for key, ttl in zip(keys_text, ttls, strict=False)]

        prev_page = page - 1
        next_page = page + 1
        base_path = request.url.path.rstrip("/")
        return await self.templates.TemplateResponse(
            request,
            "sqladmin/redis_keys.html",
            {
                "title": "Redis ключи",
                "subtitle": f"Показано до {per_page} ключей на странице",
                "rows": rows,
                "page": page,
                "per_page": per_page,
                "prev_page": prev_page if prev_page >= 1 else None,
                "next_page": next_page,
                "has_more": has_more,
                "base_path": base_path,
                "total_keys": total_keys,
            },
        )

    @expose("/redis-keys/value", methods=["GET"])
    async def value(self, request: Request) -> JSONResponse:
        redis = get_backend_redis(request)

        key = str(request.query_params.get("key") or "")
        if not key:
            return JSONResponse({"error": "Отсутствует key"}, status_code=400)

        value = await redis.get(key)
        if value is None:
            return JSONResponse({"missing": True, "value": ""})

        if isinstance(value, (bytes | bytearray)):
            value_text = value.decode("utf-8", errors="replace")
        else:
            value_text = str(value)

        return JSONResponse({"missing": False, "value": value_text})

    @expose("/redis-keys/delete", methods=["GET", "POST"])
    async def remove_key(self, request: Request) -> RedirectResponse:
        if request.method == "GET":
            base_path = request.url.path.rsplit("/", 1)[0]
            return RedirectResponse(url=base_path, status_code=303)
        form = await request.form()
        key = str(form.get("key") or "")
        page = str(form.get("page") or "1")
        redis = get_backend_redis(request)
        if key:
            await redis.delete(key)
        base_path = request.url.path.rsplit("/", 1)[0]
        return RedirectResponse(url=f"{base_path}?page={page}", status_code=303)


def setup_admin(admin: Admin) -> None:
    """Регистрируем все ModelView в SQLAdmin."""
    admin.add_view(UserAdmin)
    admin.add_view(RecipeAdmin)
    admin.add_view(CategoryAdmin)
    admin.add_view(VideoAdmin)
    admin.add_view(IngredientAdmin)
    admin.add_view(BroadcastCampaignAdmin)
    admin.add_view(BroadcastMessageAdmin)
    admin.add_view(RedisKeysAdmin)
    # admin.add_view(AdminUserAdmin)
