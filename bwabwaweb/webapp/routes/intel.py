"""Route Intel: pengguna aktif webapp (standard)."""
from fastapi import APIRouter, Depends, Request, Response

from webapp.deps import (
    get_intel_service,
    get_mu_service,
    get_open_orders_service,
    get_player_service,
    get_portfolio_service,
    get_top_traders_service,
    get_traders_service,
    require_tier,
)
from webapp.routes.rate_limit import limiter
from webapp.routes.templating import templates
from webapp.web_services.auth_service import TIER_BASIC, TIER_PRO, SessionInfo
from webapp.web_services.intel_service import IntelService
from webapp.web_services.player_service import PlayerService
from webapp.web_services.mu_service import MuService
from webapp.web_services.open_orders_service import OpenOrdersService
from webapp.web_services.portfolio_service import PortfolioService
from webapp.web_services.top_traders_service import TopTradersService
from webapp.web_services.traders_service import TradersService

router = APIRouter(prefix="/intel", tags=["intel"])


@router.get("")
def show_intel(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    intel: IntelService = Depends(get_intel_service),
) -> Response:
    context = {"active_tab": "intel", "session": session, "data": intel.get_active_users()}
    return templates.TemplateResponse(request, "intel.html", context)

@router.get("/player/{raw_name}")
async def show_player(
    request: Request,
    raw_name: str,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    player: PlayerService = Depends(get_player_service),
) -> Response:
    report = await player.get_player(raw_name)
    context = {"active_tab": "intel", "session": session, "report": report}
    return templates.TemplateResponse(request, "intel_player.html", context)


@router.get("/mu/{raw_name}")
async def show_mu(
    request: Request,
    raw_name: str,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    mu: MuService = Depends(get_mu_service),
) -> Response:
    report = await mu.get_mu(raw_name)
    context = {"active_tab": "intel", "session": session, "report": report}
    return templates.TemplateResponse(request, "intel_mu.html", context)

@router.get("/portfolio")
async def show_portfolio(
    request: Request,
    q: str = "",
    days: int = 20,
    all_history: bool = False,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    portfolio: PortfolioService = Depends(get_portfolio_service),
) -> Response:
    report = None
    if q.strip():
        report = await portfolio.get_portfolio(q.strip(), all_history, days)
    context = {
        "active_tab": "intel",
        "session": session,
        "query": q,
        "days": days,
        "all_history": all_history,
        "report": report,
    }
    return templates.TemplateResponse(request, "intel_portfolio.html", context)


@router.get("/traders")
def show_traders(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    traders: TradersService = Depends(get_traders_service),
) -> Response:
    report = traders.get_leaderboard()
    context = {"active_tab": "intel", "session": session, "report": report}
    return templates.TemplateResponse(request, "intel_traders.html", context)


@router.get("/top-traders")
async def show_top_traders(
    request: Request,
    q: str = "",
    days: int = 20,
    min_tx: int = 20,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    top_traders: TopTradersService = Depends(get_top_traders_service),
) -> Response:
    report = None
    if q.strip():
        report = await top_traders.get_top_traders(q.strip(), days, min_tx)
    context = {
        "active_tab": "intel",
        "session": session,
        "query": q,
        "days": days,
        "min_tx": min_tx,
        "report": report,
    }
    return templates.TemplateResponse(request, "intel_top_traders.html", context)


@router.get("/open-orders")
async def show_open_orders(
    request: Request,
    q: str = "",
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    open_orders: OpenOrdersService = Depends(get_open_orders_service),
) -> Response:
    report = None
    if q.strip():
        report = await open_orders.get_open_orders(q.strip())
    context = {
        "active_tab": "intel",
        "session": session,
        "query": q,
        "report": report,
    }
    return templates.TemplateResponse(request, "intel_open_orders.html", context)
