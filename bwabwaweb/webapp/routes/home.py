"""Route Home: ringkasan market dari snapshot harga."""

from fastapi import APIRouter, Depends, Request, Response

from webapp.deps import get_home_service, get_required_session
from webapp.routes.templating import templates
from webapp.web_services.auth_service import SessionInfo
from webapp.web_services.home_service import HomeService

router = APIRouter()


@router.get("/")
def show_home(
    request: Request,
    session: SessionInfo = Depends(get_required_session),
    home_service: HomeService = Depends(get_home_service),
) -> Response:
    context = {"active_tab": "home", "session": session, "home": home_service.get_home()}
    return templates.TemplateResponse(request, "home.html", context)
