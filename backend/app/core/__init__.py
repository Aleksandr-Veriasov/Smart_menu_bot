from backend.app.core.exceptions import setup_exception_handlers
from backend.app.core.middleware import setup_middleware, setup_observability
from backend.app.core.routes import setup_routes
from backend.app.core.static import setup_static

__all__ = [
    "setup_exception_handlers",
    "setup_middleware",
    "setup_observability",
    "setup_routes",
    "setup_static",
]
