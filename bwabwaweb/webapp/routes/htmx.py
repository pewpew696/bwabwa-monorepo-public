"""Helper kecil untuk request htmx."""
from fastapi import Request, Response
from fastapi.responses import RedirectResponse


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def redirect_to(request: Request, url: str) -> Response:
    if is_htmx(request):
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = url
        return response
    return RedirectResponse(url, status_code=303)
