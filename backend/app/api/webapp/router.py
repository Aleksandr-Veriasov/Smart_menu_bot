"""FastAPI-роутер для эндпоинтов Telegram WebApp (Mini App)."""

from fastapi import APIRouter, Header, HTTPException, Request

from backend.app.api.webapp.schemas import (
    WebAppCategoryRead,
    WebAppRecipeDraft,
    WebAppRecipePatch,
    WebAppRecipeRead,
)
from backend.app.api.webapp.services import (
    invalidate_bot_caches_best_effort,
    load_recipe_for_user,
)
from backend.app.api.webapp.tg_webapp_auth import validate_telegram_webapp_init_data
from backend.app.api.webapp.workflows import (
    apply_patch_to_recipe,
    to_read,
    update_telegram_recipe_message_best_effort,
)
from backend.app.utils.fastapi_state import get_backend_db, get_backend_redis
from packages.common_settings.settings import settings
from packages.db.repository import CategoryRepository
from packages.redis.repository import (
    CategoryCacheRepository,
    WebAppRecipeDraftCacheRepository,
)

webapp_router = APIRouter()


def _require_tg_init_data(x_tg_init_data: str | None) -> str:
    """Проверяет, что заголовок `X-TG-INIT-DATA` есть и не пустой."""

    init_data = (x_tg_init_data or "").strip()
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствует заголовок X-TG-INIT-DATA")
    return init_data


def _get_user_id(x_tg_init_data: str | None) -> int:
    """Достаёт Telegram user_id из провалидированного initData."""

    init_data = _require_tg_init_data(x_tg_init_data)
    token = settings.telegram.bot_token.get_secret_value().strip()
    user = validate_telegram_webapp_init_data(init_data, bot_token=token)
    return int(user.id)


@webapp_router.get("/categories", response_model=list[WebAppCategoryRead])
async def list_categories(
    request: Request,
    x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA"),
) -> list[WebAppCategoryRead]:
    """Список всех категорий (из кеша Redis, при необходимости с догрузкой из БД)."""

    _get_user_id(x_tg_init_data)  # только авторизация
    redis = get_backend_redis(request)

    cached = await CategoryCacheRepository.get_all_name_and_slug(redis)
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

    db = get_backend_db(request)
    async with db.session() as session:
        rows = await CategoryRepository.get_all(session)

    # Обновляем кеш в фоне запроса (best effort).
    try:
        await CategoryCacheRepository.set_all_name_and_slug(redis, rows)
    except Exception:
        pass

    return [WebAppCategoryRead(id=int(r["id"]), name=str(r["name"]), slug=str(r["slug"])) for r in rows]


@webapp_router.get("/recipes/{recipe_id}", response_model=WebAppRecipeRead)
async def get_recipe(
    recipe_id: int,
    request: Request,
    x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA"),
) -> WebAppRecipeRead:
    """Вернуть рецепт (и category_id пользователя для него) для редактирования в WebApp."""

    user_id = _get_user_id(x_tg_init_data)
    db = get_backend_db(request)
    async with db.session() as session:
        recipe, category_id = await load_recipe_for_user(session, recipe_id=int(recipe_id), user_id=int(user_id))
        return to_read(recipe, category_id=int(category_id))


@webapp_router.get("/recipes/{recipe_id}/draft", response_model=WebAppRecipeDraft)
async def get_recipe_draft(
    recipe_id: int,
    request: Request,
    x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA"),
) -> WebAppRecipeDraft:
    """Прочитать короткоживущий черновик навигации (title/category) для рецепта."""

    user_id = _get_user_id(x_tg_init_data)
    redis = get_backend_redis(request)

    db = get_backend_db(request)
    async with db.session() as session:
        await load_recipe_for_user(session, recipe_id=int(recipe_id), user_id=int(user_id))

    data = await WebAppRecipeDraftCacheRepository.get(redis, user_id=int(user_id), recipe_id=int(recipe_id)) or {}
    return WebAppRecipeDraft(title=data.get("title"), category_id=data.get("category_id"))


@webapp_router.put("/recipes/{recipe_id}/draft", response_model=WebAppRecipeDraft)
async def put_recipe_draft(
    recipe_id: int,
    payload: WebAppRecipeDraft,
    request: Request,
    x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA"),
) -> WebAppRecipeDraft:
    """Сохранить короткоживущий черновик навигации (title/category) для рецепта."""

    user_id = _get_user_id(x_tg_init_data)
    redis = get_backend_redis(request)

    db = get_backend_db(request)
    async with db.session() as session:
        await load_recipe_for_user(session, recipe_id=int(recipe_id), user_id=int(user_id))

    await WebAppRecipeDraftCacheRepository.set_merge(
        redis,
        user_id=int(user_id),
        recipe_id=int(recipe_id),
        title=payload.title,
        category_id=payload.category_id,
    )
    data = await WebAppRecipeDraftCacheRepository.get(redis, user_id=int(user_id), recipe_id=int(recipe_id)) or {}
    return WebAppRecipeDraft(title=data.get("title"), category_id=data.get("category_id"))


@webapp_router.delete("/recipes/{recipe_id}/draft")
async def delete_recipe_draft(
    recipe_id: int,
    request: Request,
    x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA"),
) -> dict:
    """Удалить черновик навигации для рецепта."""

    user_id = _get_user_id(x_tg_init_data)
    redis = get_backend_redis(request)

    await WebAppRecipeDraftCacheRepository.clear(redis, user_id=int(user_id), recipe_id=int(recipe_id))
    return {"ok": True}


@webapp_router.patch("/recipes/{recipe_id}", response_model=WebAppRecipeRead)
async def patch_recipe(
    recipe_id: int,
    payload: WebAppRecipePatch,
    request: Request,
    x_tg_init_data: str | None = Header(default=None, alias="X-TG-INIT-DATA"),
) -> WebAppRecipeRead:
    """
    Обновить поля рецепта.

    Если рецепт связан с 2+ пользователями, он считается "общим". В этом случае мы клонируем рецепт и переносим
    связь текущего пользователя на клон, чтобы не менять общий контент для других пользователей.
    """

    user_id = _get_user_id(x_tg_init_data)
    path_recipe_id = int(recipe_id)

    db = get_backend_db(request)
    async with db.session() as session:
        (
            result_recipe_id,
            title_changed,
            category_changed,
            membership_changed,
            old_category_id,
            new_category_id,
        ) = await apply_patch_to_recipe(
            session,
            recipe_id=int(recipe_id),
            user_id=int(user_id),
            payload=payload,
        )

        recipe2, category_id2 = await load_recipe_for_user(
            session,
            recipe_id=int(result_recipe_id),
            user_id=int(user_id),
        )

    await invalidate_bot_caches_best_effort(
        request,
        user_id=int(user_id),
        old_category_id=int(old_category_id),
        new_category_id=int(new_category_id),
        title_changed=bool(title_changed),
        category_changed=bool(category_changed),
        membership_changed=bool(membership_changed),
        draft_recipe_id_to_clear=int(path_recipe_id),
    )

    await update_telegram_recipe_message_best_effort(
        request,
        user_id=int(user_id),
        recipe=recipe2,
    )
    return to_read(recipe2, category_id=int(category_id2))
