"""Route Simulator: preview build, sesi, siklus, optimize (standard)."""
import asyncio

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from webapp.deps import get_market_service, get_simulator_service, require_tier
from webapp.routes.templating import templates
from webapp.web_services.auth_service import TIER_BASIC, SessionInfo
from webapp.web_services.market_service import MarketService
from webapp.web_services.simulator_service import (
    AE_LEVEL_MAX,
    ALLOWED_PILL_STATES,
    DEFAULT_PILL_STATE,
    ALLOWED_AMMO_TIERS,
    ALLOWED_RARITIES,
    COMPANY_TILE_SLOTS,
    PRODUCTION_ITEMS,
    BATTLE_BONUS_MAX,
    DEFAULT_AMMO_TIER,
    DEFAULT_FOOD,
    RANK_BONUS_MAX,
    DEFAULT_PILL,
    EQUIPMENT_SLOTS,
    EQUIPMENT_SLOTS_WEB,
    EQUIPMENT_STAT_KEYS,
    NUM_HITS_DEFAULT,
    SimulatorService,
    build_equipment_from_rarity,
    build_market_prices,
    run_cycle_impl,
    run_optimize_impl,
    run_session_impl,
)

router = APIRouter(prefix="/sim", tags=["sim"])

_PRODUCTION_ITEM_SET = set(PRODUCTION_ITEMS)


def _parse_company_tiles(form) -> list[dict]:
    """Ambil tile company dari form. Skip tile dengan AE Inactive / target invalid."""
    out: list[dict] = []
    for i in range(COMPANY_TILE_SLOTS):
        raw_ae = form.get(f"company_{i}_ae_level")
        target = str(form.get(f"company_{i}_production_target") or "").strip()
        if target not in _PRODUCTION_ITEM_SET:
            continue
        try:
            ae = int(raw_ae or 0)
        except (TypeError, ValueError):
            ae = 0
        if ae < 1 or ae > AE_LEVEL_MAX:
            continue
        out.append({"ae_level": ae, "production_target": target})
    return out


def _parse_equipment_rarity(form) -> dict:
    """Baca equip_{slot}_rarity. Kosong kalau tidak ada field."""
    slots: dict = {}
    for slot in EQUIPMENT_SLOTS_WEB:
        rr = str(form.get(f"equip_{slot}_rarity") or "").strip()
        if rr in ALLOWED_RARITIES:
            slots[slot] = rr
    return slots


@router.get("")
def show_simulator(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
) -> Response:
    # Simulator lama digantikan builder — redirect permanen.
    return RedirectResponse(url="/sim/builder", status_code=308)


@router.get("/optimize")
def show_optimize(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    simulator: SimulatorService = Depends(get_simulator_service),
) -> Response:
    """Halaman optimizer (GET) — dulu redirect 308 ke /sim/builder, sekarang
    render form optimizer langsung supaya ceklis rarity reachable via URL."""
    context = {
        "active_tab": "sim",
        "session": session,
        "skill_options": simulator.skill_options(),
        "preview": None,
        "session_result": None,
        "cycle_result": None,
        "optimize_result": None,
        "optimize_error": None,
        "optimize_forms": {},
        "production_items": PRODUCTION_ITEMS,
        "allowed_rarities": ALLOWED_RARITIES,
        "equipment_slots": EQUIPMENT_SLOTS_WEB,
    }
    return templates.TemplateResponse(request, "tools_sim.html", context)


@router.post("")
async def run_simulator(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    simulator: SimulatorService = Depends(get_simulator_service),
) -> Response:
    form = await request.form()
    try:
        char_level = int(form.get("char_level") or 1)
    except (TypeError, ValueError):
        char_level = 1

    skills: dict[str, int] = {}
    for key in simulator.skill_options():
        raw = form.get(f"skill_{key.skill_key}")
        if raw:
            try:
                skills[key.skill_key] = int(raw)
            except (TypeError, ValueError):
                skills[key.skill_key] = 0

    preview = simulator.preview(char_level, skills)
    context = {
        "active_tab": "sim",
        "session": session,
        "skill_options": simulator.skill_options(),
        "preview": preview,
    }
    return templates.TemplateResponse(request, "tools_sim.html", context)


def _parse_form_ints(form, prefix: str, keys: tuple[str, ...]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in keys:
        raw = form.get(f"{prefix}{key}")
        try:
            out[key] = int(float(raw)) if raw not in (None, "") else 0
        except (TypeError, ValueError):
            out[key] = 0
    return out


def _parse_equipment(form) -> dict:
    equipment: dict = {}
    for slot in EQUIPMENT_SLOTS:
        slot_data: dict = {}
        for stat_key in EQUIPMENT_STAT_KEYS[slot]:
            raw = form.get(f"{slot}_{stat_key}")
            try:
                value = float(raw) if raw not in (None, "") else 0.0
            except (TypeError, ValueError):
                value = 0.0
            slot_data[stat_key] = value
        equipment[slot] = slot_data
    return equipment


@router.post("/session")
async def run_simulator_session(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    simulator: SimulatorService = Depends(get_simulator_service),
    market: MarketService = Depends(get_market_service),
) -> Response:
    form = await request.form()
    try:
        char_level = int(form.get("char_level") or 1)
    except (TypeError, ValueError):
        char_level = 1
    try:
        num_hits = int(form.get("num_hits") or NUM_HITS_DEFAULT)
    except (TypeError, ValueError):
        num_hits = NUM_HITS_DEFAULT

    ammo_tier = str(form.get("ammo_tier") or DEFAULT_AMMO_TIER).strip()
    if ammo_tier not in ALLOWED_AMMO_TIERS:
        ammo_tier = DEFAULT_AMMO_TIER

    def _parse_pct(raw, hi):
        try:
            v = float(raw) if raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            v = 0.0
        return max(0.0, min(hi, v))

    rank_bonus_pct = _parse_pct(form.get("rank_bonus_pct"), RANK_BONUS_MAX)
    battle_bonus_pct = _parse_pct(form.get("battle_bonus_pct"), BATTLE_BONUS_MAX)

    cases_enabled = bool(form.get("cases_enabled"))

    pill_state = str(form.get("pill_state") or DEFAULT_PILL_STATE).strip()
    if pill_state not in ALLOWED_PILL_STATES:
        pill_state = DEFAULT_PILL_STATE
    companies = _parse_company_tiles(form)

    skills: dict[str, int] = {}
    for opt in simulator.skill_options():
        raw = form.get(f"skill_{opt.skill_key}")
        try:
            skills[opt.skill_key] = int(raw) if raw else 0
        except (TypeError, ValueError):
            skills[opt.skill_key] = 0

    equip_slots = _parse_equipment_rarity(form)
    if equip_slots:
        equipment_raw = build_equipment_from_rarity(equip_slots)
    else:
        equipment_raw = _parse_equipment(form)
    market_prices = build_market_prices(market.list_items())

    result = run_session_impl(
        char_level, skills, equipment_raw, num_hits,
        market_prices=market_prices, ammo_tier=ammo_tier,
        rank_bonus_pct=rank_bonus_pct, battle_bonus_pct=battle_bonus_pct,
        cases_enabled=cases_enabled, companies=companies,
        pill_state=pill_state,
    )

    context = {
        "active_tab": "sim",
        "session": session,
        "skill_options": simulator.skill_options(),
        "preview": None,
        "session_result": result,
        "char_level_form": char_level,
        "num_hits_form": result.num_hits,
        "ammo_tier_form": ammo_tier,
        "rank_bonus_form": rank_bonus_pct,
        "battle_bonus_form": battle_bonus_pct,
        "cases_enabled_form": cases_enabled,
        "pill_state_form": pill_state,
        "equip_rarity_form": equip_slots,
        "company_forms": [
            (companies[i] if i < len(companies) else {"ae_level": 0, "production_target": "Iron"})
            for i in range(COMPANY_TILE_SLOTS)
        ],
        "production_items": PRODUCTION_ITEMS,
        "equipment_form": equipment_raw,
    }
    return templates.TemplateResponse(request, "tools_sim.html", context)


@router.post("/optimize")
async def run_simulator_optimize(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    simulator: SimulatorService = Depends(get_simulator_service),
    market: MarketService = Depends(get_market_service),
) -> Response:
    from webapp.core.errors import ValidationAppError as _VAE
    form = await request.form()

    try:
        char_level = int(form.get("char_level") or 24)
    except (TypeError, ValueError):
        char_level = 24

    def _pct(raw, hi):
        try:
            v = float(raw) if raw not in (None, "") else 0.0
        except (TypeError, ValueError):
            v = 0.0
        return max(0.0, min(hi, v))

    target = str(form.get("target") or "dps").strip()
    rarity_cap = str(form.get("rarity_cap") or "Merah").strip()
    # Ceklis rarity bebas: checkbox rarity_check_{tier}. Kalau minimal 1
    # dicentang, ceklis yang menentukan (rarity_cap jadi fallback lama).
    from simulator.constants import RARITY_ORDER as _RARITY_ORDER
    checked = [r for r in _RARITY_ORDER if form.get(f"rarity_check_{r}")]
    allowed_rarities = checked if checked else None
    rank_bonus_pct = _pct(form.get("rank_bonus_pct"), RANK_BONUS_MAX)
    battle_bonus_pct = _pct(form.get("battle_bonus_pct"), BATTLE_BONUS_MAX)
    ammo_tier = str(form.get("ammo_tier") or DEFAULT_AMMO_TIER).strip()
    if ammo_tier not in ALLOWED_AMMO_TIERS:
        ammo_tier = DEFAULT_AMMO_TIER
    pill_state = str(form.get("pill_state") or DEFAULT_PILL_STATE).strip()
    if pill_state not in ALLOWED_PILL_STATES:
        pill_state = DEFAULT_PILL_STATE
    food_type = str(form.get("food_type") or DEFAULT_FOOD).strip()
    cases_enabled = bool(form.get("cases_enabled"))
    try:
        max_results = int(form.get("max_results") or 5)
    except (TypeError, ValueError):
        max_results = 5

    market_prices = build_market_prices(market.list_items())

    optimize_result = None
    optimize_error = None
    try:
        optimize_result = await asyncio.to_thread(
            run_optimize_impl,
            char_level,
            target=target,
            rarity_cap=rarity_cap,
            allowed_rarities=allowed_rarities,
            rank_bonus_pct=rank_bonus_pct,
            battle_bonus_pct=battle_bonus_pct,
            ammo_tier=ammo_tier,
            pill_state=pill_state,
            food_type=food_type,
            cases_enabled=cases_enabled,
            market_prices=market_prices,
            max_results=max_results,
        )
    except _VAE as e:
        optimize_error = str(e)

    context = {
        "active_tab": "sim",
        "session": session,
        "skill_options": simulator.skill_options(),
        "preview": None,
        "session_result": None,
        "cycle_result": None,
        "optimize_result": optimize_result,
        "optimize_error": optimize_error,
        "optimize_forms": {
            "char_level": char_level,
            "target": target,
            "rarity_cap": rarity_cap,
            "allowed_rarities": allowed_rarities or [],
            "rank_bonus_pct": rank_bonus_pct,
            "battle_bonus_pct": battle_bonus_pct,
            "ammo_tier": ammo_tier,
            "pill_state": pill_state,
            "food_type": food_type,
            "cases_enabled": cases_enabled,
            "max_results": max_results,
        },
        "production_items": PRODUCTION_ITEMS,
        "allowed_rarities": ALLOWED_RARITIES,
        "equipment_slots": EQUIPMENT_SLOTS_WEB,
    }
    return templates.TemplateResponse(request, "tools_sim.html", context)


@router.post("/cycle")
async def run_simulator_cycle(
    request: Request,
    session: SessionInfo = Depends(require_tier(TIER_BASIC)),
    simulator: SimulatorService = Depends(get_simulator_service),
    market: MarketService = Depends(get_market_service),
) -> Response:
    form = await request.form()
    try:
        char_level = int(form.get("char_level") or 1)
    except (TypeError, ValueError):
        char_level = 1

    window = str(form.get("window") or "8h").strip()
    food_type = str(form.get("food_type") or DEFAULT_FOOD).strip()
    pill = str(form.get("pill") or DEFAULT_PILL).strip()

    skills: dict[str, int] = {}
    for opt in simulator.skill_options():
        raw = form.get(f"skill_{opt.skill_key}")
        try:
            skills[opt.skill_key] = int(raw) if raw else 0
        except (TypeError, ValueError):
            skills[opt.skill_key] = 0

    equipment_raw = _parse_equipment(form)
    market_prices = build_market_prices(market.list_items())
    cycle_result = run_cycle_impl(
        char_level, skills, equipment_raw, window, food_type,
        market_prices=market_prices, pill=pill,
    )

    context = {
        "active_tab": "sim",
        "session": session,
        "skill_options": simulator.skill_options(),
        "preview": None,
        "session_result": None,
        "cycle_result": cycle_result,
        "char_level_form": char_level,
        "window_form": window,
        "food_form": food_type,
        "pill_form": pill,
    }
    return templates.TemplateResponse(request, "tools_sim.html", context)
