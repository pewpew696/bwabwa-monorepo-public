"""Handler error global: AppError, validasi, HTTPException, dan error tak terduga."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from webapp.core.errors import (
    AppError,
    InvalidPasswordError,
    NotFoundError,
    RateLimitedError,
    TierRequiredError,
    UnauthorizedError,
    ValidationAppError,
)
from webapp.core.middleware import SECURITY_HEADERS
from webapp.routes.htmx import is_htmx
from webapp.routes.templating import templates

logger = logging.getLogger("webapp.errors")

LOGIN_PATH = "/login"
GENERIC_HTTP_MESSAGE = "Permintaan tidak dapat diproses."


def _retarget(response: Response, selector: str) -> Response:
    response.headers["HX-Retarget"] = selector
    response.headers["HX-Reswap"] = "innerHTML"
    return response


def _build_retry_url(request: Request) -> str:
    if request.method != "GET":
        return ""
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def _error_response(request: Request, status_code: int, message: str) -> Response:
    context = {"message": message, "status_code": status_code}
    if is_htmx(request):
        response = templates.TemplateResponse(
            request, "error_fragment.html", context, status_code=status_code
        )
        return _retarget(response, "#toast-root")
    return templates.TemplateResponse(
        request, "error_page.html", context, status_code=status_code
    )


def _tier_response(request: Request, error: TierRequiredError) -> Response:
    if not is_htmx(request):
        return _error_response(request, error.status_code, error.public_message)
    context = {
        "message": error.public_message,
        "retry_url": _build_retry_url(request),
        "retry_target": request.headers.get("hx-target", ""),
    }
    response = templates.TemplateResponse(
        request, "modal_password.html", context, status_code=error.status_code
    )
    return _retarget(response, "#modal-root")


def _unauthorized_response(request: Request, error: UnauthorizedError) -> Response:
    if isinstance(error, InvalidPasswordError):
        return _error_response(request, error.status_code, error.public_message)
    if is_htmx(request):
        response = Response(status_code=error.status_code)
        response.headers["HX-Redirect"] = LOGIN_PATH
        return response
    return RedirectResponse(LOGIN_PATH, status_code=303)


async def handle_app_error(request: Request, error: AppError) -> Response:
    logger.info("%s: %s", type(error).__name__, error.detail)
    if isinstance(error, TierRequiredError):
        return _tier_response(request, error)
    if isinstance(error, UnauthorizedError):
        return _unauthorized_response(request, error)
    return _error_response(request, error.status_code, error.public_message)


async def handle_validation_error(
    request: Request, error: RequestValidationError
) -> Response:
    fields = [list(item["loc"]) for item in error.errors()]
    logger.info("Validasi gagal di field: %s", fields)
    return _error_response(
        request, ValidationAppError.status_code, ValidationAppError.public_message
    )


async def handle_http_exception(
    request: Request, error: StarletteHTTPException
) -> Response:
    message = (
        NotFoundError.public_message if error.status_code == 404 else GENERIC_HTTP_MESSAGE
    )
    return _error_response(request, error.status_code, message)


async def handle_unexpected_error(request: Request, error: Exception) -> Response:
    logger.exception("Error tak terduga di %s %s", request.method, request.url.path)
    response = _error_response(request, AppError.status_code, AppError.public_message)
    response.headers.update(SECURITY_HEADERS)
    return response


async def handle_rate_limit(request: Request, error: RateLimitExceeded) -> Response:
    logger.info("Rate limit terlampaui di %s", request.url.path)
    return _error_response(
        request, RateLimitedError.status_code, RateLimitedError.public_message
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit)
    app.add_exception_handler(Exception, handle_unexpected_error)
