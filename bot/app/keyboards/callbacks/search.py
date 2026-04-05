import re

from bot.app.keyboards.callbacks.shared import SharedCallbacks as SharedCB


class SearchCallbacks:
    SEARCH_RECIPES = "search:start"

    @classmethod
    def pattern_search_recipes(cls) -> str:
        return rf"^{re.escape(cls.SEARCH_RECIPES)}$"

    @classmethod
    def pattern_search_type(cls) -> str:
        return rf"^search:type:(?:{SharedCB.SEARCH_TYPE_PATTERN})$"

    @staticmethod
    def build_search_start() -> str:
        return SearchCallbacks.SEARCH_RECIPES

    @staticmethod
    def build_search_type(search_type: str) -> str:
        return f"search:type:{search_type}"

    @staticmethod
    def search_recipes() -> str:
        return SearchCallbacks.build_search_start()

    @staticmethod
    def search_type(search_type: str) -> str:
        return SearchCallbacks.build_search_type(search_type)
