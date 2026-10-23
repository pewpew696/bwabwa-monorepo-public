# builder.py
"""Route Build Optimizer /sim/builder (standard)."""
import asyncio

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from simulator.constants import PRODUCTION_CHAIN
from webapp.core.errors import ValidationAppError
from webapp.deps import (
    get_builder_service,
    get_market_service,
    get_simulator_service,
    require_tier,
)
from webapp.routes.rate_limit import build_rate_limit_key, limiter
from webapp.routes.templating import templates
from webapp.web_services.auth_service import TIER_BASIC, TIER_PRO, SessionInfo
from webapp.web_services.builder_forms import (
    ECO_SKILL_KEYS,
    MAX_COMPANY_ROWS,
    MAX_PRICE_OVERRIDE_ROWS,
    _parse_config,
    _parse_mode,
    _parse_pinned_levels,
)
from webapp.web_services.builder_import import import_player
from webapp.web_services.builder_models import ADV_STAT_MAX, KNOWN_PRICE_KEYS
from webapp.web_services.builder_service import BuilderService
from webapp.web_services.market_service import MarketService
from webapp.web_services.simulator_service import (
    ALLOWED_RARITIES,
    EQUIPMENT_SLOTS_WEB,
    EQUIPMENT_STAT_KEYS,
    SimulatorService,
    build_market_prices,
)

router = APIRouter(prefix="/sim/builder", tags=["builder"])
BUILDER_RATE_LIMIT = "30/minute"
IMPORT_RATE_LIMIT = "10/minute"  # ketat: tiap hit = beberapa call API WarEra
USERNAME_PATTERN = r"^[A-Za-z0-9 _-]+$"


class ImportRequest(BaseModel):
    """Body JSON POST /sim/builder/import."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=40, pattern=USERNAME_PATTERN)


@router.get("")
def show_builder(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    simulator: SimulatorService = Depends(get_simulator_service),
    builder: BuilderService = Depends(get_builder_service),
    market: MarketService = Depends(get_market_service),
) -> Response:
    try:
        db_prices = build_market_prices(market.list_items())
    except Exception:
        db_prices = {}
    context = {
        "active_tab": "sim",
        "session": session,
        "skill_options": simulator.skill_options(),
        "allowed_rarities": ALLOWED_RARITIES,
        "equipment_slots": EQUIPMENT_SLOTS_WEB,
        "equipment_stat_keys": EQUIPMENT_STAT_KEYS,
        "stat_max": ADV_STAT_MAX,
        "eco_skill_keys": ECO_SKILL_KEYS,
        "production_items": sorted(PRODUCTION_CHAIN.keys()),
        "max_company_rows": MAX_COMPANY_ROWS,
        "price_keys": sorted(KNOWN_PRICE_KEYS),
        "max_price_override_rows": MAX_PRICE_OVERRIDE_ROWS,
        "db_prices": db_prices,
        "pins": builder.get_pins(build_rate_limit_key(request)),
    }
    return templates.TemplateResponse(request, "tools_builder.html", context)


@router.post("/calculate")
@limiter.limit(BUILDER_RATE_LIMIT)
async def calculate_builder(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    builder: BuilderService = Depends(get_builder_service),
    market: MarketService = Depends(get_market_service),
) -> Response:
    form = await request.form()
    skey = build_rate_limit_key(request)
    try:
        builder.set_pins(skey, _parse_pinned_levels(form, builder.get_pins(skey)))
    except ValueError as exc:
        raise ValidationAppError(str(exc))
    pins = builder.get_pins(skey)
    config = _parse_config(form, pins)
    market_prices = build_market_prices(market.list_items())
    try:
        result = await asyncio.to_thread(builder.calculate_build, config, market_prices)
    except NotImplementedError as exc:
        raise ValidationAppError(str(exc))
    except ValueError as exc:
        raise ValidationAppError(str(exc))
    compare = builder.add_to_compare(skey, result)
    context = {
        "active_tab": "sim",
        "session": session,
        "result": result,
        "compare": compare,
        "pins": pins,
    }
    return templates.TemplateResponse(request, "partials/builder_result.html", context)


@router.post("/import")
@limiter.limit(IMPORT_RATE_LIMIT)
async def import_builder_player(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
) -> Response:
    """Username WarEra -> JSON auto-fill builder (skills, gear, company, wage)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=422, content={"error": "body harus JSON"})
    try:
        payload = ImportRequest(**body)
    except ValidationError:
        return JSONResponse(status_code=422, content={
            "error": "username tidak valid (1-40 karakter: huruf, angka, spasi, -, _)",
        })
    try:
        result = await import_player(payload.username)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    except Exception:
        return JSONResponse(status_code=502, content={
            "error": "gagal menghubungi API WarEra, coba lagi nanti",
        })
    return JSONResponse(content=result)


@router.post("/clear")
@limiter.limit(BUILDER_RATE_LIMIT)
async def clear_builder(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_PRO)),
    builder: BuilderService = Depends(get_builder_service),
) -> Response:
    form = await request.form()
    mode = _parse_mode(form.get("mode"))
    skey = build_rate_limit_key(request)
    builder.clear_compare(skey, mode)
    # Pin TIDAK ikut dihapus — pin = preferensi sesi, bukan isi keranjang.
    context = {
        "active_tab": "sim",
        "session": session,
        "result": None,
        "compare": [],
        "pins": builder.get_pins(skey),
    }
    return templates.TemplateResponse(request, "partials/builder_result.html", context)
