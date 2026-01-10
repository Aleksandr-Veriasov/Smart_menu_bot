import logging
import re

from bot.app.core.recipes_mode import RecipeMode

logger = logging.getLogger(__name__)

# slug может содержать a-z, 0-9, _ и -
CB_RE = re.compile(r"^(?P<category>[a-z0-9][a-z0-9_-]*?)(?:_(?P<mode>show|random|edit|save))?$")

CB_RE_C = re.compile(r"^(?P<category>[a-z0-9][a-z0-9_-]*)_save(?:\:\d+)?$")

CB_RE_M = re.compile(r"^recipes(?:_(?P<mode>show|random|edit))?$")
CB_CAT_MODE_ID = re.compile(r"^([a-z0-9][a-z0-9_-]*)_(show|random|edit)_(\d+)$")
CB_CHANGE_CATEGORY = re.compile(r"^change_category:(?P<category>[a-z0-9][a-z0-9_-]*)$")


def parse_category_mode(cb: str) -> tuple[str, RecipeMode] | None:
    """
    Возвращает (category_slug, mode) или None, если формат не подошёл.
    """
    logger.debug(f"⏩⏩⏩ m = {cb}")
    m = CB_RE.fullmatch((cb or "").lower())
    logger.debug(f"⏩⏩⏩ m = {m.group(0) if m else None}")
    if not m:
        return None
    category = m.group("category")
    mode_str = m.group("mode")
    logger.debug(f"⏩⏩⏩ mode_str = {mode_str}, category = {category}")
    mode = RecipeMode(mode_str)
    return category, mode


def parse_category(cb: str) -> str | None:
    """
    Возвращает (category_slug) или None, если формат не подошёл.
    """
    logger.debug(f"⏩⏩⏩ m = {cb}")
    m = CB_RE_C.fullmatch((cb or "").lower())
    logger.debug(f"⏩⏩⏩ m = {m}")
    if not m:
        return None
    category = m.group("category")
    return category


def parse_mode(cb: str) -> RecipeMode | None:
    """
    Возвращает (mode) или None, если формат не подошёл.
    """
    m = CB_RE_M.fullmatch((cb or "").lower())
    logger.debug(f"⏩⏩⏩ m = {m}")
    if not m:
        return None
    mode_str = m.group("mode")
    logger.debug(f"⏩⏩⏩ mode_str = {mode_str}")
    mode = RecipeMode(mode_str)
    return mode


def parse_category_mode_id(cb: str) -> tuple[str, str, int] | None:
    """
    Возвращает (category, mode, obj_id) или None, если формат не подошёл.
    mode: 'show' | 'random' | 'edit'
    """
    m = CB_CAT_MODE_ID.fullmatch((cb or "").lower().strip())
    if not m:
        return None
    category, mode, obj_id = m.groups()
    return category, mode, int(obj_id)


def parse_change_category(cb: str) -> str | None:
    """
    Возвращает category_slug для смены категории или None.
    """
    m = CB_CHANGE_CATEGORY.fullmatch((cb or "").lower().strip())
    if not m:
        return None
    return m.group("category")
