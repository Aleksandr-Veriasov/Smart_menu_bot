import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def safe_remove(path: str | None) -> None:
    """Безопасно удаляет файл, если он существует."""
    if not path:
        return
    p = Path(path)
    try:
        if p.exists():
            p.unlink()  # Python 3.10 ок
            logger.debug("🧹 Удалён временный файл: %s", p)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("Не удалось удалить %s: %s", p, e)
