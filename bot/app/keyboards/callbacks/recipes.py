import re

from bot.app.core.recipes_mode import RecipeMode
from bot.app.keyboards.callbacks.shared import SharedCallbacks as SharedCB


class RecipeCallbacks:
    RECIPES_BOOK = "recipes:book"

    @classmethod
    def pattern_recipes_menu(cls) -> str:
        return rf"^recipes:menu:(?:{SharedCB.MENU_MODE_PATTERN})$"

    @classmethod
    def pattern_recipes_book(cls) -> str:
        return rf"^{re.escape(cls.RECIPES_BOOK)}$"

    @classmethod
    def pattern_book_category(cls) -> str:
        return rf"^recipes:bookcat:{SharedCB.SLUG_PATTERN}$"

    @classmethod
    def pattern_recipe_choice(cls) -> str:
        return rf"^recipes:choice:(?P<category>{SharedCB.SLUG_PATTERN}|book_[a-z0-9][a-z0-9_-]*):(?P<mode>show|random):(?P<recipe_id>\d+)$"

    @classmethod
    def pattern_category_mode(cls) -> str:
        return (
            rf"^recipes:cat:(?P<category>{SharedCB.SLUG_PATTERN}):(?P<mode>show|random|save)(?::(?P<pipeline_id>\d+))?$"
        )

    @classmethod
    def pattern_category_menu(cls) -> str:
        return rf"^recipes:cat:(?P<category>{SharedCB.SLUG_PATTERN}):(?P<mode>{SharedCB.MENU_MODE_PATTERN})$"

    @classmethod
    def pattern_save_category(cls) -> str:
        return rf"^recipes:cat:(?P<category>{SharedCB.SLUG_PATTERN}):save:(?P<pipeline_id>\d+)$"

    @classmethod
    def pattern_pagination(cls) -> str:
        return rf"^page:(?P<page>\d+)(?::(?P<category>{SharedCB.SLUG_PATTERN}|book_[a-z0-9][a-z0-9_-]*):(?P<mode>{SharedCB.LIST_MODE_PATTERN}))?$"

    @classmethod
    def pattern_recipe_delete(cls) -> str:
        return r"^recipe:delete:\d+$"

    @classmethod
    def pattern_recipe_share(cls) -> str:
        return r"^recipe:share:\d+$"

    @classmethod
    def pattern_share_back(cls) -> str:
        return r"^recipe:shareback:\d+$"

    @classmethod
    def pattern_recipe_add(cls) -> str:
        return r"^recipe:add:\d+$"

    @classmethod
    def pattern_recipe_add_category(cls) -> str:
        return rf"^recipe:addcat:\d+:{SharedCB.SLUG_PATTERN}$"

    @classmethod
    def pattern_save_recipe(cls) -> str:
        return r"^save:start:\d+$"

    @classmethod
    def pattern_cancel_save_recipe(cls, *, with_id: bool = True) -> str:
        if with_id:
            return r"^save:cancel:\d+$"
        return r"^save:cancel$"

    @classmethod
    def parse_recipes_menu_mode(cls, data: str | None) -> RecipeMode | None:
        match = re.fullmatch(r"recipes:menu:(show|random)", (data or "").lower())
        return RecipeMode(match.group(1)) if match else None

    @classmethod
    def parse_category_mode(cls, data: str | None) -> tuple[str, RecipeMode] | None:
        match = re.fullmatch(cls.pattern_category_mode(), (data or "").lower())
        if not match:
            return None
        return match.group("category"), RecipeMode(match.group("mode"))

    @classmethod
    def parse_save_category(cls, data: str | None) -> tuple[str, int | None] | None:
        match = re.fullmatch(cls.pattern_category_mode(), (data or "").lower())
        if not match:
            return None
        pipeline_id = match.group("pipeline_id")
        return match.group("category"), int(pipeline_id) if pipeline_id else None

    @classmethod
    def parse_recipe_choice(cls, data: str | None) -> tuple[str, str, int] | None:
        match = re.fullmatch(cls.pattern_recipe_choice(), (data or "").lower().strip())
        if not match:
            return None
        return match.group("category"), match.group("mode"), int(match.group("recipe_id"))

    @classmethod
    def parse_pagination(cls, data: str | None) -> tuple[int, str | None, str | None] | None:
        match = re.fullmatch(cls.pattern_pagination(), data or "")
        if not match:
            return None
        return int(match.group("page")), match.group("category"), match.group("mode")

    @classmethod
    def parse_book_category(cls, data: str | None) -> str | None:
        match = re.fullmatch(rf"recipes:bookcat:({SharedCB.SLUG_PATTERN})", (data or "").lower())
        return match.group(1) if match else None

    @classmethod
    def parse_recipe_delete(cls, data: str | None) -> int | None:
        return SharedCB._parse_prefixed_int(data, "recipe:delete:")

    @classmethod
    def parse_recipe_share(cls, data: str | None) -> int | None:
        return SharedCB._parse_prefixed_int(data, "recipe:share:")

    @classmethod
    def parse_share_back(cls, data: str | None) -> int | None:
        return SharedCB._parse_prefixed_int(data, "recipe:shareback:")

    @classmethod
    def parse_recipe_add(cls, data: str | None) -> int | None:
        return SharedCB._parse_prefixed_int(data, "recipe:add:")

    @classmethod
    def parse_recipe_add_category(cls, data: str | None) -> tuple[int, str] | None:
        match = re.fullmatch(rf"recipe:addcat:(\d+):({SharedCB.SLUG_PATTERN})", data or "")
        if not match:
            return None
        return int(match.group(1)), match.group(2)

    @classmethod
    def parse_save_recipe(cls, data: str | None) -> int | None:
        return SharedCB._parse_prefixed_int(data, "save:start:")

    @classmethod
    def parse_cancel_save_recipe(cls, data: str | None) -> int | None:
        return SharedCB._parse_prefixed_int(data, "save:cancel:")

    @staticmethod
    def build_recipes_menu(mode: RecipeMode = RecipeMode.SHOW) -> str:
        return f"recipes:menu:{mode.value}"

    @staticmethod
    def build_recipes_book() -> str:
        return RecipeCallbacks.RECIPES_BOOK

    @staticmethod
    def build_recipes_random(category_slug: str) -> str:
        return f"recipes:cat:{category_slug}:random"

    @staticmethod
    def build_recipes_category(category_slug: str, mode: RecipeMode, pipeline_id: int = 0) -> str:
        if mode is RecipeMode.SAVE:
            return f"recipes:cat:{category_slug}:{mode.value}:{pipeline_id}"
        return f"recipes:cat:{category_slug}:{mode.value}"

    @staticmethod
    def build_recipes_choice(category_slug: str, mode: str, recipe_id: int) -> str:
        return f"recipes:choice:{category_slug}:{mode}:{recipe_id}"

    @staticmethod
    def build_page(page: int, category_slug: str | None = None, mode: str | None = None) -> str:
        if category_slug and mode:
            return f"page:{page}:{category_slug}:{mode}"
        return f"page:{page}"

    @staticmethod
    def build_recipe_delete(recipe_id: int) -> str:
        return f"recipe:delete:{recipe_id}"

    @staticmethod
    def build_recipe_share(recipe_id: int) -> str:
        return f"recipe:share:{recipe_id}"

    @staticmethod
    def build_recipe_share_back(recipe_id: int) -> str:
        return f"recipe:shareback:{recipe_id}"

    @staticmethod
    def build_recipe_add(recipe_id: int) -> str:
        return f"recipe:add:{recipe_id}"

    @staticmethod
    def build_recipe_add_category(recipe_id: int, slug: str) -> str:
        return f"recipe:addcat:{recipe_id}:{slug}"

    @staticmethod
    def build_save_start(pipeline_id: int) -> str:
        return f"save:start:{pipeline_id}"

    @staticmethod
    def build_save_cancel(pipeline_id: int | None = None) -> str:
        return "save:cancel" if pipeline_id is None else f"save:cancel:{pipeline_id}"

    @staticmethod
    def build_recipes_book_category(category_slug: str) -> str:
        return f"recipes:bookcat:{category_slug}"

    @staticmethod
    def build_recipe_back(page: int, category_slug: str, mode: str) -> str:
        return RecipeCallbacks.build_page(page, category_slug, mode)

    @staticmethod
    def recipes_menu(mode: RecipeMode = RecipeMode.SHOW) -> str:
        return RecipeCallbacks.build_recipes_menu(mode)

    @staticmethod
    def recipes_book() -> str:
        return RecipeCallbacks.build_recipes_book()

    @staticmethod
    def random_recipe(category_slug: str) -> str:
        return RecipeCallbacks.build_recipes_random(category_slug)

    @staticmethod
    def category_mode(category_slug: str, mode: RecipeMode, pipeline_id: int = 0) -> str:
        return RecipeCallbacks.build_recipes_category(category_slug, mode, pipeline_id)

    @staticmethod
    def recipe_choice(category_slug: str, mode: str, recipe_id: int) -> str:
        return RecipeCallbacks.build_recipes_choice(category_slug, mode, recipe_id)

    @staticmethod
    def pagination(page: int, category_slug: str | None = None, mode: str | None = None) -> str:
        return RecipeCallbacks.build_page(page, category_slug, mode)

    @staticmethod
    def recipe_delete(recipe_id: int) -> str:
        return RecipeCallbacks.build_recipe_delete(recipe_id)

    @staticmethod
    def recipe_share(recipe_id: int) -> str:
        return RecipeCallbacks.build_recipe_share(recipe_id)

    @staticmethod
    def share_back(recipe_id: int) -> str:
        return RecipeCallbacks.build_recipe_share_back(recipe_id)

    @staticmethod
    def recipe_add(recipe_id: int) -> str:
        return RecipeCallbacks.build_recipe_add(recipe_id)

    @staticmethod
    def recipe_add_category(recipe_id: int, slug: str) -> str:
        return RecipeCallbacks.build_recipe_add_category(recipe_id, slug)

    @staticmethod
    def save_recipe(pipeline_id: int) -> str:
        return RecipeCallbacks.build_save_start(pipeline_id)

    @staticmethod
    def cancel_save_recipe(pipeline_id: int | None = None) -> str:
        return RecipeCallbacks.build_save_cancel(pipeline_id)

    @staticmethod
    def book_category(category_slug: str) -> str:
        return RecipeCallbacks.build_recipes_book_category(category_slug)

    @staticmethod
    def recipe_back(page: int, category_slug: str, mode: str) -> str:
        return RecipeCallbacks.build_recipe_back(page, category_slug, mode)
