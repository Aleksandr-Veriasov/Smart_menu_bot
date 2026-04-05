import re

from bot.app.keyboards.callbacks.shared import SharedCallbacks as SharedCB


class UrlCallbacks:
    @classmethod
    def pattern_url_pick(cls) -> str:
        return rf"^url:pick:{SharedCB.SID_PATTERN}:\d+$"

    @classmethod
    def pattern_url_list(cls) -> str:
        return rf"^url:list:{SharedCB.SID_PATTERN}$"

    @classmethod
    def pattern_url_add(cls) -> str:
        return rf"^url:add:{SharedCB.SID_PATTERN}:\d+$"

    @classmethod
    def pattern_url_add_category(cls) -> str:
        return rf"^url:addcat:{SharedCB.SID_PATTERN}:\d+:{SharedCB.SLUG_PATTERN}$"

    @classmethod
    def parse_url_pick(cls, data: str | None) -> tuple[str, int] | None:
        return SharedCB._parse_sid_and_int(data, "url:pick:")

    @classmethod
    def parse_url_add(cls, data: str | None) -> tuple[str, int] | None:
        return SharedCB._parse_sid_and_int(data, "url:add:")

    @classmethod
    def parse_url_list(cls, data: str | None) -> str | None:
        match = re.fullmatch(rf"url:list:({SharedCB.SID_PATTERN})", data or "")
        return match.group(1) if match else None

    @classmethod
    def parse_url_add_category(cls, data: str | None) -> tuple[str, int, str] | None:
        match = re.fullmatch(
            rf"url:addcat:({SharedCB.SID_PATTERN}):(\d+):({SharedCB.SLUG_PATTERN})",
            data or "",
        )
        if not match:
            return None
        return match.group(1), int(match.group(2)), match.group(3)

    @staticmethod
    def build_url_pick(sid: str, recipe_id: int) -> str:
        return f"url:pick:{sid}:{recipe_id}"

    @staticmethod
    def build_url_add(sid: str, recipe_id: int) -> str:
        return f"url:add:{sid}:{recipe_id}"

    @staticmethod
    def build_url_list(sid: str) -> str:
        return f"url:list:{sid}"

    @staticmethod
    def build_url_add_category(sid: str, recipe_id: int, slug: str) -> str:
        return f"url:addcat:{sid}:{recipe_id}:{slug}"

    @staticmethod
    def url_pick(sid: str, recipe_id: int) -> str:
        return UrlCallbacks.build_url_pick(sid, recipe_id)

    @staticmethod
    def url_add(sid: str, recipe_id: int) -> str:
        return UrlCallbacks.build_url_add(sid, recipe_id)

    @staticmethod
    def url_list(sid: str) -> str:
        return UrlCallbacks.build_url_list(sid)

    @staticmethod
    def url_add_category(sid: str, recipe_id: int, slug: str) -> str:
        return UrlCallbacks.build_url_add_category(sid, recipe_id, slug)
