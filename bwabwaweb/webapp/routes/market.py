"""Route Market: daftar item, detail chart, orderbook (standard), indikator (VIP)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from webapp.deps import (
    get_bonus_service,
    get_companies_service,
    get_fairprice_service,
    get_market_service,
    get_required_session,
    require_tier,
)
from webapp.routes.rate_limit import limiter
from webapp.routes.templating import templates
from webapp.schemas.market import OhlcBasicResponse, OhlcResponse
from webapp.web_services.auth_service import TIER_BASIC, TIER_PRO, SessionInfo
from webapp.web_services.bonus_service import BonusService
from webapp.web_services.fairprice_service import FairpriceService
from services.economy.constants import ITEM_LABELS
from webapp.web_services.market_service import DEFAULT_HOURS, MarketService
from webapp.web_services.companies_service import CompaniesService

HOURS_MIN = 1
HOURS_MAX = 2160
router = APIRouter(prefix="/market", tags=["market"])


@router.get("")
def show_list(
    request: Request,
    session: SessionInfo = Depends(get_required_session),
    market: MarketService = Depends(get_market_service),
) -> Response:
    context = {"active_tab": "market", "session": session, "items": market.list_items()}
    return templates.TemplateResponse(request, "market_list.html", context)


@router.get("/bonus")
def show_bonus(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    bonus: BonusService = Depends(get_bonus_service),
) -> Response:
    context = {"active_tab": "market", "session": session, "items": bonus.list_items()}
    return templates.TemplateResponse(request, "market_bonus.html", context)


@router.get("/item/{raw_name}")
def show_item(
    request: Request,
    raw_name: str,
    hours: int = Query(DEFAULT_HOURS, ge=HOURS_MIN, le=HOURS_MAX),
    session: SessionInfo = Depends(get_required_session),
    market: MarketService = Depends(get_market_service),
) -> Response:
    detail = market.get_item_detail(raw_name, hours)
    context = {"active_tab": "market", "session": session, "detail": detail}
    return templates.TemplateResponse(request, "market_item.html", context)


@router.get("/item/{raw_name}/orderbook")
async def show_orderbook(
    request: Request,
    raw_name: str,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    market: MarketService = Depends(get_market_service),
) -> Response:
    data = await market.fetch_orderbook_live(raw_name)
    context = {"orderbook": data}
    return templates.TemplateResponse(request, "partials/orderbook.html", context)



@router.get("/fairprice")
async def show_fairprice(
    request: Request,
    item: str = "",
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    fairprice: FairpriceService = Depends(get_fairprice_service),
) -> Response:
    report = None
    if item.strip():
        report = await fairprice.get_fairprice(item.strip())
    context = {
        "active_tab": "market",
        "session": session,
        "query": item,
        "item_options": sorted(ITEM_LABELS.values()),
        "report": report,
    }
    return templates.TemplateResponse(request, "market_fairprice.html", context)

OHLC_ALLOWED_BINS = (1, 4, 24)


BASIC_ALLOWED_HOURS = (24, 168, 720, 2160)


@router.get("/item/{raw_name}/ohlc", response_model=OhlcBasicResponse)
def show_ohlc_basic(
    request: Request,
    raw_name: str,
    hours: int = Query(720, ge=HOURS_MIN, le=HOURS_MAX),
    bin_hours: int | None = Query(None, ge=1, le=24, alias="bin"),
    session: SessionInfo = Depends(get_required_session),
    market: MarketService = Depends(get_market_service),
) -> OhlcBasicResponse:
    # BASIC: candlestick + range + bin (tanpa indikator advanced).
    if hours not in BASIC_ALLOWED_HOURS:
        hours = 720
    if bin_hours is not None and bin_hours not in OHLC_ALLOWED_BINS:
        raise HTTPException(status_code=400, detail=f"bin harus {OHLC_ALLOWED_BINS}")
    return market.get_item_ohlc_basic(raw_name, hours, bin_hours)


@router.get("/item/{raw_name}/ohlc-indicators", response_model=OhlcResponse)
def show_ohlc_vip(
    request: Request,
    raw_name: str,
    hours: int = Query(DEFAULT_HOURS, ge=HOURS_MIN, le=HOURS_MAX),
    bin_hours: int | None = Query(None, ge=1, le=24, alias="bin"),
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    market: MarketService = Depends(get_market_service),
) -> OhlcResponse:
    if bin_hours is not None:
        if bin_hours not in OHLC_ALLOWED_BINS:
            raise HTTPException(status_code=400, detail=f"bin harus {OHLC_ALLOWED_BINS}")
        if bin_hours > hours:
            raise HTTPException(status_code=400, detail="bin lebih besar dari range jam")
    return market.get_item_ohlc_bundle(raw_name, hours, bin_hours)


# --- Company Explorer ---

COMPANIES_RATE_LIMIT = "30/minute"  # pola FISCAL_RATE_LIMIT


@router.get("/companies")
@limiter.limit(COMPANIES_RATE_LIMIT)
def show_companies_list(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    companies: CompaniesService = Depends(get_companies_service),
) -> Response:
    items = companies.get_item_summary()
    context = {"active_tab": "market", "session": session, "items": items}
    return templates.TemplateResponse(request, "market_companies.html", context)


@router.get("/companies/{item_code}")
@limiter.limit(COMPANIES_RATE_LIMIT)
def show_companies_item(
    request: Request,
    item_code: str,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    companies: CompaniesService = Depends(get_companies_service),
) -> Response:
    detail = companies.get_item_breakdown(item_code)
    context = {"active_tab": "market", "session": session, "detail": detail}
    return templates.TemplateResponse(request, "market_companies_item.html", context)

