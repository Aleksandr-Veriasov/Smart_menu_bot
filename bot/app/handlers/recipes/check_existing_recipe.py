from telegram import Update
from telegram.constants import ParseMode

from bot.app.core.types import PTBContext
from bot.app.handlers.recipes.existing_by_url import (
    maybe_handle_multiple_existing_recipes,
)
from bot.app.keyboards.inlines import add_recipe_keyboard, home_keyboard
from bot.app.utils.context_helpers import get_db
from bot.app.utils.message_cache import append_message_id_to_cache
from packages.db.repository import (
    RecipeRepository,
    RecipeUserRepository,
    VideoRepository,
)


async def handle_existing_recipe(update: Update, context: PTBContext, url: str) -> bool:
    """
    Проверяет, существует ли рецепт с данным URL, и отправляет его пользователю.
    Возвращает True, если рецепт найден и отправлен, иначе False.
    """
    message = update.effective_message
    if not message:
        return False
    db = get_db(context)
    async with db.session() as session:
        videos = await VideoRepository.get_all_by_original_url(session, url, limit=20)
        if not videos:
            return False

        recipe_ids: list[int] = []
        seen: set[int] = set()
        for v in videos:
            rid = getattr(v, "recipe_id", None)
            if not rid:
                continue
            rid_i = int(rid)
            if rid_i in seen:
                continue
            seen.add(rid_i)
            recipe_ids.append(rid_i)

        if not recipe_ids:
            return False

        if len(recipe_ids) >= 2:
            return await maybe_handle_multiple_existing_recipes(
                update=update,
                context=context,
                original_url=url,
                candidates=recipe_ids,
            )

        existing = videos[0]
        if not existing or not existing.recipe_id:
            return False

        user_id = message.from_user.id if message.from_user else None
        recipe = await RecipeRepository.get_recipe_with_connections(session, int(existing.recipe_id))
        if not recipe:
            return False

        if user_id:
            await RecipeRepository.update_last_used_at(session, int(recipe.id))
            await session.commit()

        if existing.video_url:
            video_msg = await message.reply_video(existing.video_url)
            await append_message_id_to_cache(message, context, video_msg.message_id)

        ingredients_text = "\n".join(f"- {ingredient.name}" for ingredient in recipe.ingredients)
        text = (
            f"🍽 <b>Название рецепта:</b> {recipe.title}\n\n"
            f"📝 <b>Рецепт:</b>\n{recipe.description}\n\n"
            f"🥦 <b>Ингредиенты:</b>\n{ingredients_text}"
        )
        already_linked = False
        if user_id:
            already_linked = await RecipeUserRepository.is_linked(session, int(recipe.id), int(user_id))
        reply_markup = home_keyboard() if already_linked else add_recipe_keyboard(int(recipe.id))
        header = "Этот рецепт у Вас уже сохранён ✅" if already_linked else "Этот рецепт уже есть в нашем каталоге ✅"
        reply = await message.reply_text(
            f"{header}\n\n{text}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
        await append_message_id_to_cache(message, context, reply.message_id)
        return True
