"""Instance Jinja2Templates bersama (autoescape aktif) beserta filter format."""

from fastapi.templating import Jinja2Templates

from webapp.core.settings import PROJECT_ROOT
from webapp.routes.formatting import FILTERS

templates = Jinja2Templates(directory=str(PROJECT_ROOT / "webapp" / "templates"))
templates.env.filters.update(FILTERS)

# CSP nonce per-request (dipasang middleware di request.state.csp_nonce).
# Semua caller pakai pola TemplateResponse(request, name, context), jadi
# wrapper ini menyisipkan csp_nonce ke context otomatis — template tinggal
# pakai {{ csp_nonce }} tanpa pass manual per route.
_orig_template_response = templates.TemplateResponse


def _template_response_with_nonce(request, name, context=None, *args, **kwargs):
    context = dict(context) if context else {}
    if hasattr(request.state, "csp_nonce"):
        context.setdefault("csp_nonce", request.state.csp_nonce)
    return _orig_template_response(request, name, context, *args, **kwargs)


templates.TemplateResponse = _template_response_with_nonce
