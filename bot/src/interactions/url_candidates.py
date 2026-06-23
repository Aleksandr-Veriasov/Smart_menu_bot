import secrets

from aiogram.types import Message

from bot.src.bot_ui.messages import MessageService
from bot.src.bot_ui.url_candidates import UrlCandidateStore
from bot.src.keyboards.recipe import url_candidate_list_keyboard
from packages.services.recipe_service import RecipeService


def extract_allowed_recipe_ids(state: dict) -> list[int]:
    """
    Возвращает допустимые recipe_id из сохранённого state с сохранением порядка.
    Игнорирует невалидные значения и дубликаты.
    """
    recipe_ids: list[int] = []
    seen: set[int] = set()
    for value in state.get("recipe_ids") or []:
        if not isinstance(value, int | str) or not str(value).isdigit():
            continue
        recipe_id = int(value)
        if recipe_id in seen:
            continue
        seen.add(recipe_id)
        recipe_ids.append(recipe_id)
    return recipe_ids


async def maybe_show_url_candidate_list(
    *,
    message: Message,
    recipe_service: RecipeService,
    message_service: MessageService,
    url_candidate_store: UrlCandidateStore,
    original_url: str,
    candidates: list[int],
) -> bool:
    """
    Если кандидатов >= 2, сохраняет список в Redis и отправляет пользователю кнопки с названиями.
    Возвращает True, если обработано.
    """
    if not message.from_user:
        return False
    if len(candidates) < 2:
        return False

    recipe_titles = await recipe_service.get_titles_for_ids(candidates)

    sid = secrets.token_urlsafe(6).replace("-", "").replace("_", "")
    payload = {"url": original_url, "recipe_ids": [int(x) for x in candidates], "v": 1}
    await url_candidate_store.set(sid=sid, payload=payload)

    sent = await message_service.send_and_track(
        message.bot,
        chat_id=message.chat.id,
        text="По этой ссылке найдено несколько рецептов. Выберите нужный:",
        reply_markup=url_candidate_list_keyboard(sid, recipe_titles),
    )
    await url_candidate_store.set_merge(
        sid=sid,
        patch={
            "chat_id": int(sent.chat.id),
            "list_message_id": int(sent.message_id),
            "video_message_id": None,
            "recipe_message_id": None,
        },
    )
    return True
