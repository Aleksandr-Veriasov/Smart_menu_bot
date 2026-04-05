import re


class NavCallbacks:
    START = "nav:start"
    CANCEL = "nav:cancel"
    DELETE = "nav:delete"
    SAVE_CHANGES = "edit:save"

    @classmethod
    def pattern_start(cls) -> str:
        return rf"^{re.escape(cls.START)}$"

    @classmethod
    def pattern_cancel(cls) -> str:
        return rf"^{re.escape(cls.CANCEL)}$"

    @classmethod
    def pattern_delete(cls) -> str:
        return rf"^{re.escape(cls.DELETE)}$"

    @staticmethod
    def build_nav_start() -> str:
        return NavCallbacks.START

    @staticmethod
    def build_nav_cancel() -> str:
        return NavCallbacks.CANCEL

    @staticmethod
    def build_nav_delete() -> str:
        return NavCallbacks.DELETE

    @staticmethod
    def build_edit_save() -> str:
        return NavCallbacks.SAVE_CHANGES

    @staticmethod
    def start() -> str:
        return NavCallbacks.build_nav_start()

    @staticmethod
    def cancel() -> str:
        return NavCallbacks.build_nav_cancel()

    @staticmethod
    def delete() -> str:
        return NavCallbacks.build_nav_delete()

    @staticmethod
    def save_changes() -> str:
        return NavCallbacks.build_edit_save()
