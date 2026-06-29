import logging

from fastapi import Request
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

logger = logging.getLogger(__name__)

_templates = Jinja2Templates(directory="backend/web/templates")

_TITLES = {
    400: "Некорректный запрос",
    401: "Требуется авторизация",
    403: "Доступ запрещён",
    404: "Страница не найдена",
    405: "Метод не поддерживается",
    422: "Ошибка валидации",
    429: "Слишком много запросов",
    500: "Внутренняя ошибка сервера",
    502: "Ошибка шлюза",
    503: "Сервис недоступен",
}


def _error_response(request: Request, status_code: int, detail: str) -> HTMLResponse:
    return _templates.TemplateResponse(
        request=request,
        name="errors/error.html",
        context={
            "status_code": status_code,
            "title": _TITLES.get(status_code, "Ошибка"),
            "detail": detail,
        },
        status_code=status_code,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> HTMLResponse:
    return _error_response(request, exc.status_code, exc.detail or "")


async def lookup_error_handler(request: Request, exc: LookupError) -> HTMLResponse:
    return _error_response(request, 404, str(exc))


async def value_error_handler(request: Request, exc: ValueError) -> HTMLResponse:
    return _error_response(request, 422, str(exc))


async def internal_error_handler(request: Request, exc: Exception) -> HTMLResponse:
    logger.exception("Unhandled exception: %s", exc)
    return _error_response(request, 500, "Что-то пошло не так. Попробуйте позже.")
