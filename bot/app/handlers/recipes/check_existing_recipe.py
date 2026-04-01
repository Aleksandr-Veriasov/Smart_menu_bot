import logging

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.constants import ParseMode

from bot.app.core.types import PTBContext
from bot.app.handlers.recipes.existing_by_url import (
    maybe_handle_multiple_existing_recipes,
)
from bot.app.keyboards.inlines import add_recipe_keyboard, home_keyboard
from bot.app.utils.context_helpers import get_db
from bot.app.utils.message_cache import reply_text_and_cache, reply_video_and_cache
from bot.app.utils.message_utils import build_existing_recipe_text
from packages.db.models import Recipe, Video
from packages.db.repository import (
    RecipeRepository,
    RecipeUserRepository,
    VideoRepository,
)

logger = logging.getLogger(__name__)

EXISTING_RECIPE_VIDEOS_LIMIT = 20


def collect_recipe_candidates(videos: list[Video]) -> tuple[Video | None, list[int]]:
    """Возвращает первое валидное видео и уникальные recipe_id в порядке появления."""
    first_video: Video | None = None
    recipe_ids: list[int] = []
    seen: set[int] = set()
    for video in videos:
        recipe_id = getattr(video, "recipe_id", None)
        if not recipe_id:
            continue
        if first_video is None:
            first_video = video
        if recipe_id in seen:
            continue
        seen.add(recipe_id)
        recipe_ids.append(recipe_id)
    return first_video, recipe_ids


async def get_single_recipe_data(
    session: AsyncSession,
    message,
    first_video: Video,
) -> tuple[Recipe, bool] | None:
    """Загружает рецепт для single-match сценария и проверяет связь с пользователем."""
    recipe = await RecipeRepository.get_recipe_with_connections(session, first_video.recipe_id)
    if not recipe:
        logger.warning("Рецепт recipe_id=%s не найден для video_id=%s", first_video.recipe_id, first_video.id)
        return None

    user_id = message.from_user.id if message.from_user else None
    already_linked = False
    if user_id:
        already_linked = await RecipeUserRepository.is_linked(session, recipe.id, user_id)
    return recipe, already_linked


async def handle_existing_recipe(update: Update, context: PTBContext, url: str) -> bool:
    """
    Проверяет, существует ли рецепт с данным URL, и отправляет его пользователю.
    Возвращает True, если рецепт найден и отправлен, иначе False.
    """
    message = update.effective_message
    if not message:
        return False
    db = get_db(context)
    first_video: Video | None = None
    recipe: Recipe | None = None
    recipe_id: int | None = None
    already_linked = False

    async with db.session() as session:
        # 1. Ищем все видео по исходному URL.
        videos = await VideoRepository.get_all_by_original_url(
            session,
            url,
            limit=EXISTING_RECIPE_VIDEOS_LIMIT,
        )
        if not videos:
            return False

        # 2. За один проход собираем первое валидное видео и уникальные recipe_id.
        first_video, recipe_ids = collect_recipe_candidates(videos)
        if not first_video:
            logger.warning("Не найдено ни одного видео с recipe_id для original_url=%s", url)
            return False

        if not recipe_ids:
            return False

        # 3. Если рецептов несколько, передаём управление в сценарий выбора.
        if len(recipe_ids) >= 2:
            return await maybe_handle_multiple_existing_recipes(
                update=update,
                context=context,
                original_url=url,
                candidates=recipe_ids,
            )

        # 4. Для single-match сценария загружаем рецепт по recipe_id первого видео.
        recipe_id = first_video.recipe_id
        single_recipe_data = await get_single_recipe_data(session, message, first_video)
        if single_recipe_data is None:
            return False
        recipe, already_linked = single_recipe_data

    if not recipe or recipe_id is None or not first_video:
        return False

    # 5. После закрытия сессии готовим данные для ответа пользователю.
    video_url = first_video.video_url
    text = build_existing_recipe_text(recipe)

    # 6. Сначала отправляем видео, если оно есть.
    if video_url:
        await reply_video_and_cache(message, context, video_url)

    # 7. Затем отправляем текст рецепта с подходящей клавиатурой.
    reply_markup = home_keyboard() if already_linked else add_recipe_keyboard(recipe_id)
    header = "Этот рецепт у Вас уже сохранён ✅" if already_linked else "Этот рецепт уже есть в нашем каталоге ✅"
    await reply_text_and_cache(
        message,
        context,
        f"{header}\n\n{text}",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )
    return True
