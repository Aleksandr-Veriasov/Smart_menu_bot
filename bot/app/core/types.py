from typing import Any, TypeAlias, TypedDict

from telegram.ext import Application, CallbackContext, ExtBot, JobQueue

from packages.app_state import AppState


class BotData(TypedDict):
    state: AppState


PTBContext: TypeAlias = CallbackContext[
    ExtBot[None],
    dict[Any, Any],
    dict[Any, Any],
    BotData,
]

PTBApp: TypeAlias = Application[
    ExtBot[None],
    PTBContext,
    dict[Any, Any],  # user_data
    dict[Any, Any],  # chat_data
    BotData,  # bot_data
    JobQueue[PTBContext],
]

__all__ = ["AppState", "BotData", "PTBContext", "PTBApp"]
