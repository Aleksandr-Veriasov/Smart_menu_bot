from backend.app.core.middleware import setup_middleware
from backend.app.core.routes import setup_routes
from backend.app.core.static import setup_static

__all__ = [
    "setup_middleware",
    "setup_routes",
    "setup_static",
]
