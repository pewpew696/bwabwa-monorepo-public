"""Route Territory: leaderboard pajak + detail negara (standard)."""
import logging
from fastapi import APIRouter, Depends, Query, Request, Response

from webapp.deps import (
    get_country_stock_service,
    get_fiscal_service,
    get_required_session,
    get_territory_service,
    require_tier,
)
from webapp.routes.rate_limit import limiter
from webapp.routes.templating import templates
from webapp.web_services.auth_service import TIER_BASIC, TIER_PRO, SessionInfo
from webapp.web_services.territory_service import (
    EVENTS_DEFAULT_LIMIT,
    LEADERBOARD_DEFAULT_LIMIT,
    TerritoryService,
)
from webapp.web_services.country_stock_service import CountryStockService
from webapp.web_services.fiscal_service import FiscalService

router = APIRouter(prefix="/territory", tags=["territory"])
logger = logging.getLogger("webapp.error")

FISCAL_RATE_LIMIT = "30/minute"


@router.get("")
def show_leaderboard(
    request: Request,
    from_date: str = Query("", alias="from"),
    to_date: str = Query("", alias="to"),
    limit: int = Query(LEADERBOARD_DEFAULT_LIMIT),
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    territory: TerritoryService = Depends(get_territory_service),
) -> Response:
    data = territory.get_leaderboard(from_date, to_date, limit)
    context = {"active_tab": "territory", "session": session, "data": data}
    return templates.TemplateResponse(request, "territory.html", context)


@router.get("/country/{raw_name}")
def show_country(
    request: Request,
    raw_name: str,
    from_date: str = Query("", alias="from"),
    to_date: str = Query("", alias="to"),
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    territory: TerritoryService = Depends(get_territory_service),
) -> Response:
    try:
        data = territory.get_country(raw_name, from_date, to_date)
    except Exception as exc:
        # "negara tidak ditemukan" → tampilkan pesan user-friendly, bukan 500
        msg = str(exc).lower()
        if "tidak ditemukan" in msg or "not found" in msg:
            data = {
                "country_name": raw_name,
                "from": "",
                "to": "",
                "summary": {},
                "daily": [],
                "error": f"Country '{raw_name}' not found.",
            }
        else:
            logger.exception("territory.country failed for %r", raw_name)
            data = {
                "country_name": raw_name,
                "from": "",
                "to": "",
                "summary": {},
                "daily": [],
                "error": "Country data is temporarily unavailable. Please try again later.",
            }
    context = {"active_tab": "territory", "session": session, "data": data}
    return templates.TemplateResponse(request, "territory_country.html", context)


@router.get("/country/{raw_name}/events")
def show_events(
    request: Request,
    raw_name: str,
    limit: int = Query(EVENTS_DEFAULT_LIMIT),
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    territory: TerritoryService = Depends(get_territory_service),
) -> Response:
    data = territory.get_events(raw_name, limit)
    return templates.TemplateResponse(request, "partials/territory_events.html", {"data": data})

@router.get("/country-stock")
async def show_country_stock(
    request: Request,
    q: str = "",
    days: int = 20,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    country_stock: CountryStockService = Depends(get_country_stock_service),
) -> Response:
    report = None
    if q.strip():
        report = await country_stock.get_country_stock(q.strip(), days)
    context = {
        "active_tab": "territory",
        "session": session,
        "query": q,
        "days": days,
        "report": report,
    }
    return templates.TemplateResponse(request, "territory_country_stock.html", context)


@router.get("/tax-calc")
@limiter.limit(FISCAL_RATE_LIMIT)
def show_tax_calc(
    request: Request,
    window: str = "24h",
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    fiscal: FiscalService = Depends(get_fiscal_service),
) -> Response:
    # Tax Calc diisi dashboard Fiscal Monitor: leaderboard pajak global.
    overview = fiscal.get_overview(window)
    context = {"active_tab": "territory", "session": session, "overview": overview}
    return templates.TemplateResponse(request, "territory_tax_calc.html", context)


@router.get("/tax-calc/{country_id}")
@limiter.limit(FISCAL_RATE_LIMIT)
def show_tax_calc_country(
    request: Request,
    country_id: str,
    window: str = "24h",
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    fiscal: FiscalService = Depends(get_fiscal_service),
) -> Response:
    detail = fiscal.get_country_detail(country_id, window)
    context = {"active_tab": "territory", "session": session, "detail": detail}
    return templates.TemplateResponse(request, "territory_tax_calc_country.html", context)

