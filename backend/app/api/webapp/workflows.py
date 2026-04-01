"""
Сценарии (workflows) для Telegram WebApp.

В этом модуле находится бизнес-логика и оркестрация шагов:
- валидация и нормализация пользовательского ввода
- правила редактирования "общих" рецептов (2+ пользователей): клонирование и перенос связи
- формирование ответа для WebApp
- по возможности: обновление последнего сообщения с рецептом в Telegram

Низкоуровневые операции с БД/Redis живут в `backend.app.api.webapp.services`.
"""

import asyncio
from html import escape as html_escape

import requests
import sqlalchemy as sa
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.webapp.schemas import WebAppRecipePatch, WebAppRecipeRead
from backend.app.api.webapp.services import count_recipe_users, load_recipe_for_user
from backend.app.utils.fastapi_state import get_backend_redis_optional
from packages.common_settings.settings import settings
from packages.db.models import Recipe, RecipeIngredient, Video
from packages.db.repository import (
    IngredientRepository,
    RecipeIngredientRepository,
    RecipeRepository,
    RecipeUserRepository,
)
from packages.db.schemas import RecipeUpdate
from packages.redis.repository import (
    RecipeActionCacheRepository,
    UserMessageIdsCacheRepository,
)


def parse_ingredient_names(text: str) -> list[str]:
    """
    Разобрать ингредиенты, введённые пользователем в WebApp.

    Правила:
    - одна непустая строка = один ингредиент
    - пробелы по краям строки убираем
    - дубликаты удаляем, порядок сохраняем
    """

    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    parts: list[str] = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts.append(line)
    return list(dict.fromkeys(parts))


def to_read(recipe: Recipe, *, category_id: int) -> WebAppRecipeRead:
    """Преобразовать модель БД в схему ответа WebApp."""

    ingredients = [str(i.name) for i in (recipe.ingredients or []) if getattr(i, "name", None)]
    return WebAppRecipeRead(
        id=int(recipe.id),
        title=str(recipe.title),
        description=recipe.description,
        category_id=int(category_id),
        ingredients=ingredients,
    )


def validate_title(raw: str) -> str:
    """Провалидировать и нормализовать название рецепта."""

    title = (raw or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    return title


async def clone_recipe_for_user(
    session: AsyncSession,
    *,
    original: Recipe,
    user_id: int,
    category_id: int,
    payload: WebAppRecipePatch,
) -> tuple[int, bool]:
    """
    Клонировать рецепт (когда он "общий" на нескольких пользователей) и перенести текущего пользователя на клон.

    Возвращает:
    - new_recipe_id: id нового рецепта
    - category_changed_for_user: изменился ли category_id пользователя для этого рецепта
    """

    new_title = validate_title(payload.title) if payload.title is not None else str(original.title)
    new_description = payload.description if payload.description is not None else original.description
    new_category_id = int(payload.category_id) if payload.category_id is not None else int(category_id)
    category_changed = int(new_category_id) != int(category_id)

    if payload.ingredients_text is not None:
        names = parse_ingredient_names(payload.ingredients_text)
    else:
        names = [str(i.name) for i in (original.ingredients or []) if getattr(i, "name", None)]

    new_recipe = await RecipeRepository.create_basic(session, new_title, new_description)

    if getattr(original, "video", None) is not None and original.video is not None:
        session.add(
            Video(
                recipe_id=int(new_recipe.id),
                video_url=str(original.video.video_url),
                original_url=original.video.original_url,
            )
        )

    if names:
        id_by_name = await IngredientRepository.bulk_get_or_create(session, names)
        await RecipeIngredientRepository.bulk_link(session, int(new_recipe.id), id_by_name.values())

    await RecipeUserRepository.link_user(session, int(new_recipe.id), int(user_id), int(new_category_id))
    await RecipeUserRepository.unlink_user(session, int(original.id), int(user_id))

    return int(new_recipe.id), category_changed


async def apply_patch_to_recipe(
    session: AsyncSession,
    *,
    recipe_id: int,
    user_id: int,
    payload: WebAppRecipePatch,
) -> tuple[int, bool, bool, bool, int, int]:
    """
    Основной write path: обновляет рецепт, при необходимости клонирует.

    Возвращает:
    (result_recipe_id, title_changed, category_changed, membership_changed, old_category_id, new_category_id)
    """

    recipe, category_id = await load_recipe_for_user(session, recipe_id=int(recipe_id), user_id=int(user_id))
    old_category_id = int(category_id)

    users_count = await count_recipe_users(session, recipe_id=int(recipe.id))
    is_shared_recipe = users_count >= 2

    title_changed = False
    category_changed = False
    membership_changed = False

    # В WebApp главная форма всегда отправляет title (и его наличие не означает реального изменения).
    # Поэтому для "общих" рецептов (2+ пользователей) форкаем только если контент ДЕЙСТВИТЕЛЬНО меняется.
    title_will_change = False
    if payload.title is not None:
        requested_title = validate_title(payload.title)
        title_will_change = requested_title != (recipe.title or "")

    description_will_change = False
    if payload.description is not None:
        description_will_change = payload.description != recipe.description

    ingredients_will_change = False
    if payload.ingredients_text is not None:
        requested_names = parse_ingredient_names(payload.ingredients_text)
        current_names = [str(i.name) for i in (recipe.ingredients or []) if getattr(i, "name", None)]
        ingredients_will_change = requested_names != current_names

    content_will_change = title_will_change or description_will_change or ingredients_will_change

    if is_shared_recipe and content_will_change:
        # В "общем" рецепте нельзя менять контент, не затронув других пользователей, поэтому форкаем.
        new_recipe_id, cat_changed = await clone_recipe_for_user(
            session,
            original=recipe,
            user_id=int(user_id),
            category_id=int(old_category_id),
            payload=payload,
        )
        membership_changed = True
        category_changed = cat_changed
        recipe_id = int(new_recipe_id)
    else:
        # Категория хранится в RecipeUser, так что её можно менять без форка даже для "общих" рецептов.
        if payload.title is not None and title_will_change:
            title = validate_title(payload.title)
            title_changed = True
            await RecipeRepository.update_title(session, int(recipe_id), title)

        if payload.description is not None and description_will_change:
            await RecipeRepository.update(session, int(recipe_id), RecipeUpdate(description=payload.description))

        if payload.category_id is not None:
            requested_category_id = int(payload.category_id)
            category_changed = requested_category_id != old_category_id
            if category_changed:
                await RecipeRepository.update_category(
                    session,
                    recipe_id=int(recipe_id),
                    user_id=int(user_id),
                    category_id=requested_category_id,
                )
                category_id = requested_category_id

        if payload.ingredients_text is not None and ingredients_will_change:
            names = parse_ingredient_names(payload.ingredients_text)
            await session.execute(sa.delete(RecipeIngredient).where(RecipeIngredient.recipe_id == int(recipe_id)))
            if names:
                id_by_name = await IngredientRepository.bulk_get_or_create(session, names)
                await RecipeIngredientRepository.bulk_link(session, int(recipe_id), id_by_name.values())

    _, new_category_id = await load_recipe_for_user(session, recipe_id=int(recipe_id), user_id=int(user_id))
    return (
        int(recipe_id),
        title_changed,
        category_changed,
        membership_changed,
        int(old_category_id),
        int(new_category_id),
    )


async def update_telegram_recipe_message_best_effort(
    request: Request,
    *,
    user_id: int,
    recipe: Recipe,
) -> None:
    """Обновить последнее сообщение с рецептом в Telegram; ошибки игнорируются (по возможности)."""

    redis = get_backend_redis_optional(request)
    if redis is None:
        return

    cached = await UserMessageIdsCacheRepository.get_user_message_ids(redis, int(user_id))
    if not cached:
        return
    chat_id = cached["chat_id"]
    message_ids = cached["message_ids"]
    if not message_ids:
        return
    target_message_id = int(message_ids[-1])

    recipes_state = await RecipeActionCacheRepository.get(redis, int(user_id), "recipes_state") or {}
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
            [{"text": "🗑 Удалить рецепт", "callback_data": f"delete_recipe_{int(recipe.id)}"}],
            [{"text": "⏪ Назад", "callback_data": f"next_{page}:{category_slug}:{mode}"}],
            [{"text": "🏠 На главную", "callback_data": "start"}],
        ]
    }

    safe_title = html_escape(recipe.title or "")
    safe_description = html_escape(recipe.description or "")
    ingredients_text = "\n".join(f"- {html_escape(i.name or '')}" for i in (recipe.ingredients or []))
    body = (
        f"🍽 <b>Название рецепта:</b> {safe_title}\n\n"
        f"📝 <b>Рецепт:</b>\n{safe_description}\n\n"
        f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
    )
    text = "✅ Рецепт обновлен.\n\n" + body

    token = settings.telegram.bot_token.get_secret_value().strip()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/editMessageText"

    payload = {
        "chat_id": chat_id,
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
