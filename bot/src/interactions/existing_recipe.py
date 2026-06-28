from aiogram.enums import ParseMode
from aiogram.types import Message

from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.url_candidates import UrlCandidateStore
from bot.src.interactions.url_candidates import maybe_show_url_candidate_list
from bot.src.keyboards.menu import home_keyboard
from bot.src.keyboards.recipe import add_recipe_keyboard
from bot.src.utils.recipe_text import build_existing_recipe_text
from packages.services.recipe_service import RecipeService

EXISTING_RECIPE_VIDEOS_LIMIT = 20


async def show_existing_recipe_if_found(
    message: Message,
    recipe_service: RecipeService,
    message_service: MessageService,
    url_candidate_store: UrlCandidateStore,
    url: str,
) -> bool:
    """
    Проверяет, существует ли рецепт с данным URL, и отправляет его пользователю.
    Возвращает True, если рецепт найден и отправлен, иначе False.
    """
    user_id = message.from_user.id if message.from_user else None
    match = await recipe_service.find_existing_by_url(url, user_id, limit=EXISTING_RECIPE_VIDEOS_LIMIT)

    if not match.recipe_ids:
        return False

    # Несколько рецептов по одному URL — передаём управление в сценарий выбора.
    if len(match.recipe_ids) >= 2:
        return await maybe_show_url_candidate_list(
            message=message,
            recipe_service=recipe_service,
            message_service=message_service,
            url_candidate_store=url_candidate_store,
            original_url=url,
            candidates=match.recipe_ids,
        )

    recipe = match.recipe
    if recipe is None:
        return False

    recipe_id = match.recipe_ids[0]
    text = build_existing_recipe_text(recipe)

    # Сначала отправляем видео, если оно есть.
    if match.video_url:
        await message_service.answer_video_and_track(message, match.video_url)

    # Затем текст рецепта с подходящей клавиатурой.
    reply_markup = home_keyboard() if match.already_linked else add_recipe_keyboard(recipe_id)
    header = "Этот рецепт у Вас уже сохранён ✅" if match.already_linked else "Этот рецепт уже есть в нашем каталоге ✅"
    await message_service.answer_and_track(
        message,
        f"{header}\n\n{text}",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )
    return True
