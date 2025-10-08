import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.app.handlers.recipes.edit_delete_recipe import (
    conversation_edit_recipe,
)
from bot.app.handlers.recipes.pagination import handler_pagination
from bot.app.handlers.recipes.recipes_menu import (
    recipe_choice,
    recipes_from_category,
    recipes_menu,
    upload_recipe,
)
from bot.app.handlers.recipes.save_recipe import save_recipe_handlers
from bot.app.handlers.user import user_help, user_start
from bot.app.handlers.video import video_link

logger = logging.getLogger(__name__)

video_link_pattern = (
    r'(https?://)?(www\.)?'
    r'(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|vimeo\.com)/\S+'
)


def setup_handlers(app: Application) -> None:
    """ Регистрирует все обработчики в приложении. """

    logger.info('Регистрация обработчиков...')
    app.add_handler(CommandHandler('start', user_start))
    app.add_handler(CommandHandler('help', user_help))
    # pattern='^(edit|delete)_recipe_(\d+)$'
    app.add_handler(conversation_edit_recipe())
    # pattern='^save_recipe$'
    app.add_handler(save_recipe_handlers())
    app.add_handler(MessageHandler(
        filters.Regex(video_link_pattern) & filters.TEXT,
        video_link
    ))
    app.add_handler(CallbackQueryHandler(
        user_help, pattern='^help$'
    ))
    app.add_handler(CallbackQueryHandler(
        user_start, pattern='^start$'
    ))
    app.add_handler(CallbackQueryHandler(
        upload_recipe, pattern='^upload_recipe$'
    ))
    app.add_handler(CallbackQueryHandler(
        recipes_menu,
        pattern=r'^recipes_(?:show|random|edit)$'
    ))
    app.add_handler(CallbackQueryHandler(
        handler_pagination, pattern=r'^(next|prev)_\d+$'
    ))
    app.add_handler(CallbackQueryHandler(
        recipe_choice,
        pattern=r'^([a-z0-9][a-z0-9_-]*)_(show|random|edit)_(\d+)$'
    ))
    app.add_handler(CallbackQueryHandler(
        recipes_from_category,
        pattern=r'^([a-z0-9][a-z0-9_-]*)(?:_(show|random|edit))?$'
    ))

    logger.info('Все хендлеры зарегистрированы.')
