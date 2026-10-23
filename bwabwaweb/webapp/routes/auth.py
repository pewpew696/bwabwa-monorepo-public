"""Route autentikasi. Logika di AuthService; di sini hanya HTTP dan cookie."""
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from webapp.core.settings import (
    COOKIE_IDENTITY,
    COOKIE_PENDING,
    COOKIE_UPGRADE,
    PENDING_TTL_SECONDS,
    get_settings,
)
from webapp.deps import get_auth_service, get_optional_session
from webapp.routes.error_handlers import LOGIN_PATH
from webapp.routes.htmx import redirect_to
from webapp.routes.rate_limit import limiter
from webapp.routes.templating import templates
from webapp.web_services.auth_service import AuthService, SessionInfo
from webapp.web_services.token_service import SECONDS_PER_DAY

router = APIRouter()

AUTH_RATE_LIMIT = "10/minute"
HOME_PATH = "/"
UPGRADED_EVENT = "auth-upgraded"


class PasswordForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(default="", max_length=128)


class NameForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=200)


class MeResponse(BaseModel):
    authenticated: bool
    identity: str | None
    upgraded: bool
    tier: str | None


def _set_cookie(
    response: Response, name: str, value: str, max_age: int | None = None
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("/login")
def show_login(
    request: Request, session: SessionInfo | None = Depends(get_optional_session)
) -> Response:
    if session is not None:
        return redirect_to(request, HOME_PATH)
    return templates.TemplateResponse(request, "login.html", {"active_tab": None})


@router.post("/auth")
@limiter.limit(AUTH_RATE_LIMIT)
def submit_password(
    request: Request,
    form: Annotated[PasswordForm, Form()],
    auth_service: AuthService = Depends(get_auth_service),
    identity_token: str | None = Cookie(default=None, alias=COOKIE_IDENTITY),
) -> Response:
    result = auth_service.login(form.password, identity_token)
    if not result.needs_name:
        return redirect_to(request, HOME_PATH)
    response = templates.TemplateResponse(request, "auth_name_form.html", {})
    _set_cookie(response, COOKIE_PENDING, result.pending_token, PENDING_TTL_SECONDS)
    return response


@router.post("/auth/name")
@limiter.limit(AUTH_RATE_LIMIT)
def submit_name(
    request: Request,
    form: Annotated[NameForm, Form()],
    auth_service: AuthService = Depends(get_auth_service),
    identity_token: str | None = Cookie(default=None, alias=COOKIE_IDENTITY),
    pending_token: str | None = Cookie(default=None, alias=COOKIE_PENDING),
) -> Response:
    token = auth_service.register_name(form.name, identity_token, pending_token)
    response = redirect_to(request, HOME_PATH)
    ttl_seconds = get_settings().identity_ttl_days * SECONDS_PER_DAY
    _set_cookie(response, COOKIE_IDENTITY, token, ttl_seconds)
    response.delete_cookie(COOKIE_PENDING, path="/")
    return response


@router.post("/auth/upgrade")
@limiter.limit(AUTH_RATE_LIMIT)
def submit_upgrade(
    request: Request,
    form: Annotated[PasswordForm, Form()],
    auth_service: AuthService = Depends(get_auth_service),
    identity_token: str | None = Cookie(default=None, alias=COOKIE_IDENTITY),
) -> Response:
    token, _tier = auth_service.upgrade(form.password, identity_token)
    response = Response(status_code=200)
    response.headers["HX-Trigger"] = UPGRADED_EVENT
    _set_cookie(response, COOKIE_UPGRADE, token)
    return response


@router.post("/auth/logout")
def logout(request: Request) -> Response:
    response = redirect_to(request, LOGIN_PATH)
    for cookie_name in (COOKIE_IDENTITY, COOKIE_PENDING, COOKIE_UPGRADE):
        response.delete_cookie(cookie_name, path="/")
    return response


@router.get("/auth/me", response_model=MeResponse)
def read_me(session: SessionInfo | None = Depends(get_optional_session)) -> MeResponse:
    if session is None:
        return MeResponse(authenticated=False, identity=None, upgraded=False, tier=None)
    return MeResponse(
        authenticated=True,
        identity=session.identity,
        upgraded=session.is_upgraded,
        tier=session.tier,
    )
