import asyncio
import logging
from collections.abc import Iterable
from contextlib import suppress
from html import escape

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Message
from redis.asyncio import Redis

from bot.src.bot_ui.message_ids import MessageIdsStore
from bot.src.bot_ui.messages import MessageService
from bot.src.keyboards.recipe import save_recipe_keyboard
from packages.redis.data_models import PipelineDraft
from packages.redis.repository import PipelineDraftCacheRepository
from packages.services.recipe_service import RecipeService

logger = logging.getLogger(__name__)


def _fmt_ingredients(ingredients: str | Iterable[str]) -> str:
    if isinstance(ingredients, str):
        return ingredients.strip()
    return "\n".join(f"• {escape(str(x))}" for x in ingredients)


async def send_recipe_confirmation(
    message: Message,
    *,
    recipe_service: RecipeService,
    redis: Redis,
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
    message_service = MessageService(MessageIdsStore(redis, user_id))
    repo = PipelineDraftCacheRepository(redis)
    draft = await repo.get(user_id, pipeline_id)
    original_url = draft.original_url if draft else None
    try:
        recipe_id = await recipe_service.save_recipe_draft(
            title=title,
            description=recipe,
            ingredients=ingredients,
            video_url=video_file_id,
            original_url=original_url,
        )
    except Exception as e:
        logger.exception("Ошибка при сохранении черновика рецепта: %s", e)
        error_draft = PipelineDraft(
            original_url=original_url,
            video_file_id=video_file_id,
            save_error=str(e),
        )
        await repo.set(user_id, pipeline_id, error_draft)
        return

    draft = PipelineDraft(
        title=title,
        recipe=recipe,
        ingredients=list(ingredients) if not isinstance(ingredients, str) else ingredients,
        original_url=original_url,
        video_file_id=video_file_id,
        recipe_id=recipe_id,
    )
    await repo.set(user_id, pipeline_id, draft)
    logger.debug("Черновик рецепта сохранен (pipeline_id=%s, recipe_id=%s)", pipeline_id, recipe_id)

    video_msg = None
    logger.debug(f"video_file_id={video_file_id}, title={title}")
    # 1) Видео (если есть file_id) — ждём до 10 сек
    if video_file_id:
        logger.debug("Пытаемся отправить видео пользователю (file_id=%s)", video_file_id)
        video_msg = await send_video_with_wait(
            message,
            message_service,
            video_file_id,
            total_timeout=10.0,
            check_interval=2.0,
        )

    # 2) Если не успели — мягкий фолбэк двумя сообщениями
    if video_msg is None and video_file_id:
        await message_service.answer_and_track(
            message,
            "⚠️ Видео подготовлено, но его отправка заняла слишком долго. " "Ниже отправляю текст рецепта.",
        )

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
        await message_service.answer_and_track(
            message,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=save_recipe_keyboard(pipeline_id),
            disable_web_page_preview=True,
        )
        logger.debug("Сообщение с рецептом успешно отправлено.")
    except Exception as e:
        logger.error("Ошибка при отправке текста рецепта: %s", e, exc_info=True)
        return


async def _try_reply_video(
    message: Message,
    message_service: MessageService,
    file_id: str,
) -> Message | None:
    """
    Единичная попытка отправить видео по file_id. Возвращает Message или None.
    """
    try:
        return await message_service.answer_video_and_track(message, file_id)
    except TelegramNetworkError as e:
        logger.warning("Таймаут/сеть при отправке видео: %s", e)
        return None
    except Exception as e:
        logger.error("Ошибка при отправке видео: %s", e, exc_info=True)
        return None


async def send_video_with_wait(
    message: Message,
    message_service: MessageService,
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
    task = asyncio.create_task(_try_reply_video(message, message_service, file_id))
    remaining = total_timeout
    while remaining > 0:
        try:
            return await asyncio.wait_for(task, timeout=min(check_interval, remaining))
        except TimeoutError:
            remaining -= check_interval
            continue
    # дедлайн: отменяем задачу, чтобы потом видео не прилетело «вдогонку»
    if not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    return None
