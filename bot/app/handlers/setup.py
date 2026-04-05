import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.app.handlers.recipes.add_existing_recipe import (
    add_existing_recipe,
    add_existing_recipe_choose_category,
)
from bot.app.handlers.recipes.delete_recipe import conversation_delete_recipe
from bot.app.handlers.recipes.existing_by_url import (
    add_candidate_recipe,
    add_candidate_recipe_choose_category,
    show_candidate_recipe,
    show_candidates_list,
)
from bot.app.handlers.recipes.pagination import handler_pagination
from bot.app.handlers.recipes.recipes_menu import (
    recipe_choice,
    recipes_book_from_category,
    recipes_book_menu,
    recipes_from_category,
    recipes_menu,
)
from bot.app.handlers.recipes.save_recipe import save_recipe_handlers
from bot.app.handlers.recipes.search_recipes import search_recipes_conversation
from bot.app.handlers.recipes.share_link import (
    share_recipe_back_handler,
    share_recipe_link_handler,
)
from bot.app.handlers.user import user_help, user_start
from bot.app.handlers.video import video_link
from bot.app.keyboards.callbacks import (
    HelpCallbacks,
    NavCallbacks,
    RecipeCallbacks,
    UrlCallbacks,
)

logger = logging.getLogger(__name__)

video_link_pattern = (
    r"(https?://)?(www\.)?"
    r"("
    r"youtube\.com|youtu\.be|youtube\.com/shorts|tiktok\.com|vm\.tiktok\.com|"
    r"instagram\.com|pinterest\.com|pin\.it|pinterest\.co"
    r")/\S+"
)


def setup_handlers(app: Application) -> None:
    """Регистрирует все обработчики в приложении."""

    logger.info("Регистрация обработчиков...")
    app.add_handler(CommandHandler("start", user_start))
    app.add_handler(CommandHandler("help", user_help))
    # pattern='^(edit|delete)_recipe_(\d+)$'
    app.add_handler(conversation_delete_recipe())
    # pattern='^save_recipe$'
    app.add_handler(save_recipe_handlers())
    # pattern='^search_recipes$'
    app.add_handler(search_recipes_conversation())
    app.add_handler(MessageHandler(filters.Regex(video_link_pattern) & filters.TEXT, video_link))
    app.add_handler(CallbackQueryHandler(user_help, pattern=HelpCallbacks.pattern_help()))
    app.add_handler(CallbackQueryHandler(user_start, pattern=NavCallbacks.pattern_start()))
    app.add_handler(CallbackQueryHandler(add_existing_recipe, pattern=RecipeCallbacks.pattern_recipe_add()))
    app.add_handler(
        CallbackQueryHandler(add_existing_recipe_choose_category, pattern=RecipeCallbacks.pattern_recipe_add_category())
    )
    app.add_handler(CallbackQueryHandler(show_candidate_recipe, pattern=UrlCallbacks.pattern_url_pick()))
    app.add_handler(CallbackQueryHandler(show_candidates_list, pattern=UrlCallbacks.pattern_url_list()))
    app.add_handler(CallbackQueryHandler(add_candidate_recipe, pattern=UrlCallbacks.pattern_url_add()))
    app.add_handler(
        CallbackQueryHandler(add_candidate_recipe_choose_category, pattern=UrlCallbacks.pattern_url_add_category())
    )
    app.add_handler(CallbackQueryHandler(recipes_menu, pattern=RecipeCallbacks.pattern_recipes_menu()))
    app.add_handler(CallbackQueryHandler(recipes_book_menu, pattern=RecipeCallbacks.pattern_recipes_book()))
    app.add_handler(CallbackQueryHandler(recipes_book_from_category, pattern=RecipeCallbacks.pattern_book_category()))
    app.add_handler(
        CallbackQueryHandler(
            handler_pagination,
            pattern=RecipeCallbacks.pattern_pagination(),
        )
    )
    app.add_handler(CallbackQueryHandler(share_recipe_link_handler, pattern=RecipeCallbacks.pattern_recipe_share()))
    app.add_handler(CallbackQueryHandler(share_recipe_back_handler, pattern=RecipeCallbacks.pattern_share_back()))
    app.add_handler(CallbackQueryHandler(recipe_choice, pattern=RecipeCallbacks.pattern_recipe_choice()))
    app.add_handler(CallbackQueryHandler(recipes_from_category, pattern=RecipeCallbacks.pattern_category_menu()))

    logger.info("Все хендлеры зарегистрированы.")
