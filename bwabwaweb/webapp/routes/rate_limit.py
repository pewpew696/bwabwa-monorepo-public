"""Rate limiter slowapi: kunci per identitas, fallback ke IP."""
from fastapi import Request
from slowapi import Limiter

from webapp.core.settings import COOKIE_IDENTITY
from webapp.deps import get_token_service, read_client_ip


def build_rate_limit_key(request: Request) -> str:
    payload = get_token_service().read_identity(request.cookies.get(COOKIE_IDENTITY))
    if payload:
        return f"identity:{payload['identity_id']}"
    return f"ip:{read_client_ip(request)}"


limiter = Limiter(key_func=build_rate_limit_key)
