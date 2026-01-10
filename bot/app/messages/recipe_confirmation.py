import asyncio
import logging
from collections.abc import Iterable
from contextlib import suppress
from html import escape

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut

from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import keyboard_save_recipe
from bot.app.services.ingredients_parser import parse_ingredients
from bot.app.services.save_recipe import save_recipe_draft_service
from bot.app.utils.context_helpers import get_db, get_redis_cli
from bot.app.utils.message_cache import append_message_id_to_cache
from packages.redis.repository import PipelineDraftCacheRepository

# Включаем логирование
logger = logging.getLogger(__name__)


def _fmt_ingredients(ingredients: str | Iterable[str]) -> str:
    if isinstance(ingredients, str):
        return ingredients.strip()
    return "\n".join(f"• {escape(str(x))}" for x in ingredients)


async def send_recipe_confirmation(
    message: Message,
    context: PTBContext,
    title: str,
    recipe: str,
    ingredients: str | Iterable[str],
    video_file_id: str,
    pipeline_id: int,
) -> None:
    """
    Отправляет пользователю видео (по file_id) и сообщение с рецептом
    + инлайн-кнопки подтверждения/отмены. Данные для последующего сохранения
    кладём в Redis-черновик.
    """
    if message.from_user is None:
        logger.warning("Пользователь не найден (from_user is None)")
        return
    user_id = message.from_user.id
    redis = get_redis_cli(context)
    draft = await PipelineDraftCacheRepository.get(redis, user_id, pipeline_id) or {}
    original_url = draft.get("original_url")
    ingredients_raw = parse_ingredients(ingredients) if isinstance(ingredients, str) else list(ingredients)
    db = get_db(context)
    try:
        async with db.session() as session:
            recipe_id = await save_recipe_draft_service(
                session,
                title=title,
                description=recipe,
                ingredients_raw=ingredients_raw,
                video_url=video_file_id,
                original_url=original_url,
            )
    except Exception as e:
        logger.exception("Ошибка при сохранении черновика рецепта: %s", e)
        error_draft = {
            "original_url": original_url,
            "video_file_id": video_file_id,
            "save_error": str(e),
        }
        await PipelineDraftCacheRepository.set(redis, user_id, pipeline_id, error_draft)
        return

    draft = {
        "title": title,
        "recipe": recipe,
        "ingredients": (list(ingredients) if not isinstance(ingredients, str) else ingredients),
        "original_url": original_url,
        "video_file_id": video_file_id,
        "recipe_id": recipe_id,
    }
    await PipelineDraftCacheRepository.set(redis, user_id, pipeline_id, draft)
    logger.debug("Черновик рецепта сохранен (pipeline_id=%s, recipe_id=%s)", pipeline_id, recipe_id)

    video_msg = None
    logger.debug(f"video_file_id = {video_file_id} ,title = {title},")
    # 1) Видео (если есть file_id) — ждём до 10 сек
    if video_file_id:
        logger.debug("Пытаемся отправить видео пользователю (file_id=%s)", video_file_id)
        video_msg = await send_video_with_wait(message, video_file_id, total_timeout=10.0, check_interval=2.0)
        if video_msg is not None:
            await append_message_id_to_cache(message, context, video_msg.message_id)

    # 2) Если не успели — мягкий фолбэк двумя сообщениями
    if video_msg is None and video_file_id:
        warn_msg = await message.reply_text(
            "⚠️ Видео подготовлено, но его отправка заняла слишком долго. " "Ниже отправляю текст рецепта.",
        )
        await append_message_id_to_cache(message, context, warn_msg.message_id)

    # 3) Текст (экранируем только пользовательские поля)
    title_html = escape(title).strip() or "Без названия"
    recipe_html = escape(recipe).strip() or "—"
    ingr_html = _fmt_ingredients(ingredients)

    text = (
        f"🍽 <b>Название рецепта:</b>\n{title_html}\n\n"
        f"📝 <b>Рецепт:</b>\n{recipe_html}\n\n"
        f"🥦 <b>Ингредиенты:</b>\n{ingr_html}\n\n"
    )

    try:
        # Первый кусок — с кнопками
        reply = await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard_save_recipe(pipeline_id=pipeline_id),
            disable_web_page_preview=True,
        )
        await append_message_id_to_cache(message, context, reply.message_id)
        logger.debug("Сообщение с рецептом успешно отправлено.")
    except Exception as e:
        logger.error("Ошибка при отправке текста рецепта: %s", e, exc_info=True)
        return


async def _try_reply_video(message: Message, file_id: str) -> Message | None:
    """
    Единичная попытка отправить видео по file_id. Возвращает Message или None.
    """
    try:
        # timeouts можно подправить при необходимости
        return await message.reply_video(
            video=file_id,
            allow_sending_without_reply=True,
            read_timeout=60,  # читаем ответ Bot API
            connect_timeout=30,
            pool_timeout=30,
        )
    except (TimedOut, NetworkError) as e:
        logger.warning("Timeout/Network при отправке видео: %s", e)
        return None
    except Exception as e:
        logger.error("Ошибка при отправке видео: %s", e, exc_info=True)
        return None


async def send_video_with_wait(
    message: Message,
    file_id: str,
    *,
    total_timeout: float = 10.0,
    check_interval: float = 2.0,
) -> Message | None:
    """
    Запускает отправку видео и ждёт её завершения не более total_timeout
    секунд, проверяя каждые check_interval. Если не успели — отменяет задачу
    и возвращает None.
    """
    task = asyncio.create_task(_try_reply_video(message, file_id))
    remaining = total_timeout
    try:
        while remaining > 0:
            try:
                return await asyncio.wait_for(task, timeout=min(check_interval, remaining))
            except asyncio.TimeoutError:
                remaining -= check_interval
                # просто ждём дальше
                continue
        # дедлайн: отменяем задачу, чтобы потом видео не прилетело «вдогонку»
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return None
    finally:
        # если задача завершилась — всё ок, ничего не делаем
        pass
