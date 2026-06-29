from fastapi import FastAPI
from fastapi.exceptions import HTTPException

from backend.app.handlers.exception_handlers import (
    http_exception_handler,
    internal_error_handler,
    lookup_error_handler,
    value_error_handler,
)


def setup_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(LookupError, lookup_error_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(Exception, internal_error_handler)
