"""Отправка сообщений в Telegram из media_worker (без aiogram)."""

import logging

from packages.notifications.edit_throttle import EditThrottle
from packages.notifications.formatting import (
    format_progress_bar,
    format_recipe_html,
    save_keyboard_dict,
)
from packages.notifications.tg_http import TgBotHttpClient, format_error_text

logger = logging.getLogger(__name__)


class MediaWorkerNotifier:
    """Обновляет прогресс-сообщение и отправляет финальную карточку рецепта."""

    def __init__(self, bot_token: str, min_edit_interval: float = 1.0) -> None:
        self._tg = TgBotHttpClient(bot_token)
        self._throttle = EditThrottle(min_edit_interval)

    def edit_progress(self, chat_id: int, message_id: int, pct: int, label: str = "") -> None:
        """Редактировать прогресс-сообщение с троттлингом."""
        self._throttle.wait_sync()
        text = format_progress_bar(pct, label)
        if self._tg.edit_message(chat_id, message_id, text):
            self._throttle.mark()

    def send_error(self, chat_id: int, message_id: int | None, text: str) -> None:
        """Поставить ❌ в прогресс-сообщение (или отправить новое, если id нет)."""
        self._tg.edit_or_send(chat_id, message_id, format_error_text(text))

    def send_recipe_card(
        self,
        chat_id: int,
        *,
        title: str,
        recipe: str,
        ingredients: list[str] | str,
        pipeline_id: int,
    ) -> int | None:
        """Отправить карточку рецепта с кнопками «Сохранить / Отмена»."""
        return self._tg.send_message(
            chat_id,
            format_recipe_html(title, recipe, ingredients),
            parse_mode="HTML",
            reply_markup=save_keyboard_dict(pipeline_id),
        )
