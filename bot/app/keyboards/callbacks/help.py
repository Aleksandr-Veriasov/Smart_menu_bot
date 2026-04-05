import re


class HelpCallbacks:
    HELP_SHOW = "help:show"

    @classmethod
    def pattern_help(cls) -> str:
        return r"^help:(?:show|topic:[a-z_]+)$"

    @classmethod
    def parse_help_topic(cls, data: str | None) -> str | None:
        match = re.fullmatch(r"help:topic:([a-z_]+)", data or "")
        return match.group(1) if match else None

    @staticmethod
    def build_help_show(topic: str | None = None) -> str:
        return HelpCallbacks.HELP_SHOW if not topic else f"help:topic:{topic}"

    @staticmethod
    def help(topic: str | None = None) -> str:
        return HelpCallbacks.build_help_show(topic)
