"""Middleware: request_id, header keamanan (CSP + nonce), dan access log."""
import logging
import secrets
import time
import uuid

from fastapi import FastAPI, Request

from webapp.core.logging import request_id_var

logger = logging.getLogger("webapp.access")


def _csp_with_nonce(nonce: str) -> str:
    return (
        "default-src 'self'; script-src 'self' 'nonce-" + nonce + "'; style-src 'self'; "
        "img-src 'self' data: https://media.warera.io; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )

# Fallback tanpa nonce (dipakai kalau response dibuat di luar middleware,
# mis. exception handler yang jalan sebelum state terisi).
CONTENT_SECURITY_POLICY = _csp_with_nonce("REQUEST_NONCE_PLACEHOLDER")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}
STATIC_PREFIX = "/static/"


def install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        # Nonce CSP per-request: inline <script> di template wajib pakai
        # nonce="{{ request.state.csp_nonce }}" — tanpa itu script diblokir.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        try:
            response = await call_next(request)
            if not request.url.path.startswith(STATIC_PREFIX):
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "%s %s -> %s (%.0f ms)",
                    request.method,
                    request.url.path,
                    response.status_code,
                    elapsed_ms,
                )
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        response.headers["Content-Security-Policy"] = _csp_with_nonce(nonce)
        for header_name, header_value in SECURITY_HEADERS.items():
            response.headers[header_name] = header_value
        return response
