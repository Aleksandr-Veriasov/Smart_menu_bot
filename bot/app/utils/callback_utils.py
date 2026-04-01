from telegram import CallbackQuery, Update


async def get_answered_callback_query(update: Update, *, require_data: bool = False) -> CallbackQuery | None:
    """Возвращает callback_query и сразу отвечает на него."""
    callback_query = update.callback_query
    if not callback_query:
        return None
    if require_data and not callback_query.data:
        return None
    await callback_query.answer()
    return callback_query
