from telegram import Message
from telegram.constants import ParseMode

from bot.app.core.types import PTBContext
from bot.app.keyboards.inlines import add_recipe_keyboard, home_keyboard
from bot.app.utils.context_helpers import get_db
from packages.db.repository import (
    RecipeRepository,
    RecipeUserRepository,
    VideoRepository,
)


async def handle_existing_recipe(message: Message, context: PTBContext, url: str) -> bool:
    db = get_db(context)
    async with db.session() as session:
        existing = await VideoRepository.get_by_original_url(session, url)
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
            await message.reply_video(existing.video_url)

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
        await message.reply_text(
            f"{header}\n\n{text}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
        return True
