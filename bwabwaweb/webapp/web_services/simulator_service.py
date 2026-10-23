"""Logika Simulator: validasi input + preview stats (port /api/sim/build).

Tanpa fastapi. Tidak butuh session bot — engine simulator murni.
"""
from dataclasses import dataclass

from simulator.constants import (
    AMMO_MULTIPLIERS,
    PRODUCTION_CHAIN,
    BATTLE_BONUS_CAP_NORMAL,
    CHAR_LEVEL_CAP,
    FOOD_ITEMS,
    SKILL_MAX_LEVEL,
    SKILLS,
    max_sp_at_char_level,
    RARITY_ORDER,
    SLOT_STAT_MAP,
    get_stat_range,
    total_sp_for_allocation,
)
from simulator.optimizer import BuildConfig, optimize_build
from simulator.engine import (
    calculate_base_stats,
    plan_hit_budget,
    plan_hit_budget_no_pill,
    simulate_session,
)
from webapp.core.errors import ValidationAppError

LEVEL_MIN = 1
LEVEL_MAX = CHAR_LEVEL_CAP
ALLOWED_AMMO_TIERS = tuple(AMMO_MULTIPLIERS.keys())
DEFAULT_AMMO_TIER = "ammo"
RANK_BONUS_MIN = 0.0
RANK_BONUS_MAX = 37.5
BATTLE_BONUS_MIN = 0.0
BATTLE_BONUS_MAX = BATTLE_BONUS_CAP_NORMAL * 100  # 95.0
DEFAULT_PILL_STATE = "none"
ALLOWED_PILL_STATES = ("none", "buff", "debuff")

PRODUCTION_ITEMS = tuple(PRODUCTION_CHAIN.keys())
COMPANY_TILE_SLOTS = 3
AE_LEVEL_MAX = 7
ALLOWED_RARITIES = tuple(RARITY_ORDER)
OPTIMIZE_TARGETS = ("dps", "survival", "profit", "efficiency", "balanced")
OPTIMIZE_MAX_RESULTS_MIN = 1
OPTIMIZE_MAX_RESULTS_MAX = 15
EQUIPMENT_SLOTS_WEB = ("weapon", "helmet", "chest", "pants", "boots", "gloves")
SIMULATOR_SKILLS = tuple(SKILLS.keys())


@dataclass(frozen=True)
class SkillPreview:
    skill_key: str
    name: str
    category: str
    unlock: int
    level: int
    max_level: int


@dataclass(frozen=True)
class BuildPreview:
    char_level: int
    sp_used: int
    sp_budget: int
    skills: list[SkillPreview]
    stats: dict


def _validate_level(char_level: int) -> None:
    if not isinstance(char_level, int) or char_level < LEVEL_MIN or char_level > LEVEL_MAX:
        raise ValidationAppError(f"char_level harus {LEVEL_MIN}-{LEVEL_MAX}")


def _validate_skills(skills: dict, char_level: int) -> dict:
    cleaned: dict[str, int] = {}
    for key, raw_level in skills.items():
        if key not in SKILLS:
            continue
        try:
            level = int(raw_level or 0)
        except (TypeError, ValueError):
            raise ValidationAppError(f"level skill '{key}' tidak valid")
        if level < 0 or level > SKILL_MAX_LEVEL:
            raise ValidationAppError(f"{key} maksimal level {SKILL_MAX_LEVEL}")
        unlock = SKILLS[key]["unlock"]
        if level > 0 and char_level < unlock:
            raise ValidationAppError(f"{key} butuh level karakter ≥ {unlock}")
        cleaned[key] = level
    return cleaned


def _check_sp_budget(skills: dict, char_level: int) -> int:
    sp_used = total_sp_for_allocation({k: v for k, v in skills.items() if v > 0})
    sp_budget = max_sp_at_char_level(char_level)
    if sp_used > sp_budget:
        raise ValidationAppError(f"SP melebihi budget: pakai {sp_used}, tersedia {sp_budget}")
    return sp_used


def _stats_to_dict(stats: dict) -> dict:
    return {
        "attack": stats["attack"],
        "precision": round(stats["precision_prob"], 4),
        "crit_chance": round(stats["crit_chance_prob"], 4),
        "crit_damage": round(stats["crit_dmg_mult"], 2),
        "armor_raw": stats["armor_raw"],
        "armor_effectiveness": round(stats["armor_eff"], 4),
        "dodge_raw": stats["dodge_raw"],
        "dodge_effectiveness": round(stats["dodge_eff"], 4),
        "max_hp": stats["max_hp"],
        "max_hunger": stats["max_hunger"],
        "loot_chance_pct": stats["loot_chance_pct"],
        "breakdown": stats.get("_breakdown", {}),
    }


class SimulatorService:
    def skill_options(self) -> list[SkillPreview]:
        return [
            SkillPreview(
                skill_key=key,
                name=data["name"],
                category=data["cat"],
                unlock=data["unlock"],
                level=0,
                max_level=SKILL_MAX_LEVEL,
            )
            for key, data in SKILLS.items()
        ]

    def preview(self, char_level: int, skills: dict) -> BuildPreview:
        _validate_level(char_level)
        cleaned = _validate_skills(skills, char_level)
        sp_used = _check_sp_budget(cleaned, char_level)
        sp_budget = max_sp_at_char_level(char_level)

        stats = calculate_base_stats(cleaned, {}, char_level)

        options_by_key = {opt.skill_key: opt for opt in self.skill_options()}
        skill_rows = [
            SkillPreview(
                skill_key=key,
                name=options_by_key[key].name,
                category=options_by_key[key].category,
                unlock=options_by_key[key].unlock,
                level=cleaned.get(key, 0),
                max_level=SKILL_MAX_LEVEL,
            )
            for key in SKILLS
        ]
        return BuildPreview(
            char_level=char_level,
            sp_used=sp_used,
            sp_budget=sp_budget,
            skills=skill_rows,
            stats=_stats_to_dict(stats),
        )

EQUIPMENT_SLOTS = ("weapon", "helmet", "chest", "pants", "boots", "gloves")
EQUIPMENT_STAT_KEYS = {
    "weapon": ("weapon_atk", "weapon_crit_chance"),
    "helmet": ("helmet_crit_dmg",),
    "chest": ("armor",),
    "pants": ("armor",),
    "boots": ("dodge",),
    "gloves": ("precision",),
}
NUM_HITS_MIN = 1
NUM_HITS_MAX = 10000
NUM_HITS_DEFAULT = 100


@dataclass(frozen=True)
class SessionResult:
    num_hits: int
    result: dict
    ammo_tier: str = DEFAULT_AMMO_TIER
    rank_bonus_pct: float = 0.0
    battle_bonus_pct: float = 0.0
    pill_state: str = DEFAULT_PILL_STATE
    pill_cost: float = 0.0


def build_equipment_from_rarity(slots: dict[str, str]) -> dict:
    """slots: {slot: rarity_name}. Stat = midpoint RARITY_STAT_RANGES; rarity ikut dibawa untuk wear cost."""
    out: dict = {}
    for slot, rarity in (slots or {}).items():
        if rarity not in RARITY_ORDER:
            continue
        if slot not in EQUIPMENT_SLOTS_WEB:
            continue
        stat_keys = SLOT_STAT_MAP.get(slot, [])
        stats: dict = {}
        for stat_key in stat_keys:
            rng = get_stat_range(stat_key, rarity)
            if rng is None:
                continue
            mn, mx = rng
            stats[stat_key] = round((mn + mx) / 2, 2)
        if stats:
            out[slot] = {**stats, "rarity": rarity}
    return out


def _build_equipment(raw: dict) -> dict:
    """raw: {slot: {stat_key: value, "rarity": opsional}}. Durability selalu 100 (MVP)."""
    equipment: dict = {}
    for slot in EQUIPMENT_SLOTS:
        slot_raw = raw.get(slot) or {}
        stats = {}
        for key in EQUIPMENT_STAT_KEYS[slot]:
            try:
                value = float(slot_raw.get(key) or 0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                stats[key] = value
        if stats:
            equipment[slot] = {"stats": stats, "durability": 100}
            rarity = slot_raw.get("rarity")
            if rarity in RARITY_ORDER:
                equipment[slot]["rarity"] = rarity
    return equipment


def run_session_impl(
    char_level: int, skills: dict, equipment_raw: dict, num_hits: int,
    market_prices: dict | None = None,
    ammo_tier: str = DEFAULT_AMMO_TIER,
    rank_bonus_pct: float = 0.0,
    battle_bonus_pct: float = 0.0,
    cases_enabled: bool = True,
    companies: list[dict] | None = None,
    pill_state: str = DEFAULT_PILL_STATE,
) -> SessionResult:
    _validate_level(char_level)
    cleaned = _validate_skills(skills, char_level)
    _check_sp_budget(cleaned, char_level)

    if num_hits < NUM_HITS_MIN:
        num_hits = NUM_HITS_MIN
    if num_hits > NUM_HITS_MAX:
        num_hits = NUM_HITS_MAX

    if ammo_tier not in ALLOWED_AMMO_TIERS:
        raise ValidationAppError(
            f"ammo_tier harus salah satu: {', '.join(ALLOWED_AMMO_TIERS)}"
        )
    if pill_state not in ALLOWED_PILL_STATES:
        raise ValidationAppError(
            f"pill_state harus salah satu: {', '.join(ALLOWED_PILL_STATES)}"
        )
    rank_bonus_pct = max(RANK_BONUS_MIN, min(RANK_BONUS_MAX, float(rank_bonus_pct or 0)))
    battle_bonus_pct = max(BATTLE_BONUS_MIN, min(BATTLE_BONUS_MAX, float(battle_bonus_pct or 0)))

    equipment = _build_equipment(equipment_raw)
    stats = calculate_base_stats(cleaned, equipment, char_level)
    battle_config = {
        "ammo_tier": ammo_tier,
        "pill_state": pill_state,
        "rank_bonus_pct": rank_bonus_pct,
        "battle_bonus_pct": battle_bonus_pct,
    }
    mp = dict(market_prices or {})
    if not cases_enabled:
        mp["Case 1"] = 0
        mp["Case 2"] = 0
    economy_config: dict = {"market_prices": mp}
    if companies:
        economy_config["companies"] = companies
    result = simulate_session(stats, battle_config, economy_config, num_hits, equipment=equipment)
    pill_cost = 0.0
    if pill_state == "buff":
        pill_price = float((market_prices or {}).get("Pill", 0) or 0)
        if pill_price > 0:
            pill_cost = pill_price
            result["net_profit"] = round(result.get("net_profit", 0.0) - pill_price, 2)
            result["pill_cost"] = round(pill_price, 2)

    return SessionResult(
        num_hits=num_hits, result=result, ammo_tier=ammo_tier,
        rank_bonus_pct=rank_bonus_pct, battle_bonus_pct=battle_bonus_pct,
        pill_state=pill_state, pill_cost=pill_cost,
    )

ALLOWED_WINDOWS = ("8h", "16h", "24h")
ALLOWED_FOODS = ("none",) + tuple(FOOD_ITEMS.keys())
DEFAULT_FOOD = "Steak"
ALLOWED_PILLS = ("buff", "none")
DEFAULT_PILL = "buff"
DEFAULT_DEBUFF_WEAPON = {
    "weapon": {
        "rarity": "Putih",
        "stats": {"weapon_atk": 0, "weapon_crit_chance": 0},
        "durability": 100,
    }
}


@dataclass(frozen=True)
class CycleResult:
    window: str
    food_type: str
    pill: str
    plan: dict
    phases: dict
    summary: dict
    notes: list[str]


def run_cycle_impl(
    char_level: int,
    skills: dict,
    equipment_raw: dict,
    window: str,
    food_type: str,
    market_prices: dict | None = None,
    pill: str = DEFAULT_PILL,
) -> CycleResult:
    _validate_level(char_level)
    cleaned = _validate_skills(skills, char_level)
    _check_sp_budget(cleaned, char_level)

    if window not in ALLOWED_WINDOWS:
        raise ValidationAppError(f"window harus salah satu: {', '.join(ALLOWED_WINDOWS)}")
    if food_type not in ALLOWED_FOODS:
        raise ValidationAppError(f"food_type harus salah satu: {', '.join(ALLOWED_FOODS)}")
    if pill not in ALLOWED_PILLS:
        raise ValidationAppError(f"pill harus salah satu: {', '.join(ALLOWED_PILLS)}")

    equipment = _build_equipment(equipment_raw)
    food_heal_pct = 0.0 if food_type == "none" else FOOD_ITEMS[food_type]["heal_pct"]

    stats_full = calculate_base_stats(cleaned, equipment, char_level)

    economy_config: dict = {
        "market_prices": market_prices or {},
        "food_type": food_type,
    }

    notes: list[str] = []
    phases_result: dict = {}

    if pill == "buff":
        equipment_debuff = dict(DEFAULT_DEBUFF_WEAPON)
        stats_debuff = calculate_base_stats(cleaned, equipment_debuff, char_level)
        plan = plan_hit_budget(stats_full, stats_debuff, food_heal_pct, window)
        battle_config = {"ammo_tier": "ammo", "pill_state": "buff"}

        buff_plan = plan["phases"]["buff"]
        buff_result = simulate_session(
            stats_full, battle_config, economy_config,
            num_hits=buff_plan["max_hits"], equipment=equipment,
            regen_pool=buff_plan["regen_pool"], hunger_budget=buff_plan["hunger_budget"],
        )
        phases_result["buff"] = buff_result

        if window in ("16h", "24h"):
            notes.append(
                "Fase debuff mengasumsikan hanya knife (Putih) tanpa equipment lain."
            )
            debuff_plan = plan["phases"]["debuff"]
            debuff_battle_config = dict(battle_config)
            debuff_battle_config["pill_state"] = "debuff"
            debuff_battle_config["ammo_tier"] = "none"
            debuff_result = simulate_session(
                stats_debuff, debuff_battle_config, economy_config,
                num_hits=debuff_plan["maintenance_hits"], equipment=equipment_debuff,
                starting_hp=buff_result.get("ending_hp"),
                regen_pool=debuff_plan["regen_at_risk"], hunger_budget=0,
            )
            phases_result["debuff"] = debuff_result

            if window == "24h":
                none_plan = plan["phases"]["none"]
                none_battle_config = dict(battle_config)
                none_battle_config["pill_state"] = "none"
                none_result = simulate_session(
                    stats_full, none_battle_config, economy_config,
                    num_hits=none_plan["max_hits"], equipment=equipment,
                    starting_hp=debuff_result.get("ending_hp"),
                    regen_pool=none_plan["regen_pool"], hunger_budget=none_plan["hunger_budget"],
                )
                phases_result["none"] = none_result
    else:
        plan = plan_hit_budget_no_pill(stats_full, food_heal_pct, window)
        none_plan = plan["phases"]["none"]
        none_battle_config = {"ammo_tier": "ammo", "pill_state": "none"}
        none_result = simulate_session(
            stats_full, none_battle_config, economy_config,
            num_hits=none_plan["max_hits"], equipment=equipment,
            regen_pool=none_plan["regen_pool"], hunger_budget=none_plan["hunger_budget"],
        )
        phases_result["none"] = none_result

    total_hits = sum(int(p.get("hits_completed") or 0) for p in phases_result.values())
    total_damage = sum(float(p.get("total_damage") or 0) for p in phases_result.values())
    total_net_profit = sum(float(p.get("net_profit") or 0) for p in phases_result.values())

    pill_cost = 0.0
    if pill == "buff":
        pill_price = float((market_prices or {}).get("Pill", 0) or 0)
        pill_cost = pill_price
        if pill_price <= 0:
            notes.append("Harga Pill tidak tersedia — biaya pill dianggap 0.")
    total_net_profit -= pill_cost

    if not (market_prices or {}):
        notes.append(
            "Harga market tidak tersedia — net_profit kemungkinan tidak akurat."
        )

    summary = {
        "total_max_hits_target": plan.get("total_max_hits"),
        "total_hits_completed": total_hits,
        "total_damage": round(total_damage, 2),
        "total_net_profit": round(total_net_profit, 2),
        "pill_cost": round(pill_cost, 2),
    }

    return CycleResult(
        window=window,
        food_type=food_type,
        pill=pill,
        plan=plan,
        phases=phases_result,
        summary=summary,
        notes=notes,
    )

def run_optimize_impl(
    char_level: int,
    target: str = "dps",
    rarity_cap: str = "Merah",
    allowed_rarities: list[str] | None = None,
    rank_bonus_pct: float = 0.0,
    battle_bonus_pct: float = 0.0,
    ammo_tier: str = DEFAULT_AMMO_TIER,
    pill_state: str = DEFAULT_PILL_STATE,
    food_type: str = "Steak",
    cases_enabled: bool = True,
    market_prices: dict | None = None,
    max_results: int = 5,
    quick: bool = False,
) -> dict:
    """Wrapper optimize_build untuk webapp. quick=True pakai budget kecil (test).

    allowed_rarities: ceklis rarity bebas dari user (bukan cap berurutan).
    Diprioritaskan di atas rarity_cap. Kalau diisi, minimal 1 tier valid.
    """
    _validate_level(char_level)
    if target not in OPTIMIZE_TARGETS:
        raise ValidationAppError(
            f"target harus salah satu: {', '.join(OPTIMIZE_TARGETS)}"
        )
    if rarity_cap not in RARITY_ORDER:
        raise ValidationAppError(
            f"rarity_cap harus salah satu: {', '.join(RARITY_ORDER)}"
        )
    if ammo_tier not in ALLOWED_AMMO_TIERS:
        raise ValidationAppError(
            f"ammo_tier harus salah satu: {', '.join(ALLOWED_AMMO_TIERS)}"
        )
    if pill_state not in ALLOWED_PILL_STATES:
        raise ValidationAppError(
            f"pill_state harus salah satu: {', '.join(ALLOWED_PILL_STATES)}"
        )

    # Ceklis rarity bebas: validasi + minimal 1 tier.
    checked_rarities: list[str] | None = None
    if allowed_rarities:
        checked = [r for r in RARITY_ORDER if r in set(allowed_rarities)]
        if not checked:
            raise ValidationAppError(
                f"pilih minimal 1 rarity: {', '.join(RARITY_ORDER)}"
            )
        checked_rarities = checked

    config = BuildConfig()
    config.char_level = char_level
    config.rank_bonus_pct = max(RANK_BONUS_MIN, min(RANK_BONUS_MAX, float(rank_bonus_pct or 0)))
    config.rarity_cap = rarity_cap
    config.allowed_rarities = checked_rarities
    config.target = target
    config.max_results = max(OPTIMIZE_MAX_RESULTS_MIN, min(OPTIMIZE_MAX_RESULTS_MAX, int(max_results or 5)))

    config.battle_config = {
        "ammo_tier": ammo_tier,
        "pill_state": pill_state,
        "rank_bonus_pct": config.rank_bonus_pct,
        "battle_bonus_pct": max(BATTLE_BONUS_MIN, min(BATTLE_BONUS_MAX, float(battle_bonus_pct or 0))),
        "is_revolt": False,
    }

    mp = dict(market_prices or {})
    if not cases_enabled:
        mp["Case 1"] = 0
        mp["Case 2"] = 0
    config.economy_config = {
        "food_type": food_type,
        "market_prices": mp,
        "companies": [],
        "company_count": 0,
        "ae_levels": [],
        "company_production": None,
        "weapon_rarity": "Hijau",
    }

    if quick:
        config.raw_skill_pool_size = 50
        config.skill_shortlist_size = 2
        config.equipment_beam_width = 3
        config.rng_verify_seconds = 0.1
        config.rng_verify_runs = 0
        config.rng_verify_hits_per_run = 100
    else:
        config.raw_skill_pool_size = 3000
        config.skill_shortlist_size = 15
        config.equipment_beam_width = 30
        config.rng_verify_seconds = 3.0
        # Monte Carlo per kandidat final — angka RNG asli yang stabil (mean ±
        # std), ranking final pakai mean RNG. Keputusan owner 2026-10:
        # "sevalid mungkin".
        config.rng_verify_runs = 20
        config.rng_verify_hits_per_run = 200

    return optimize_build(config)


def build_market_prices(latest_rows: list[dict]) -> dict[str, float]:
    """Konversi hasil queries_market.get_items_latest() -> {item_name: price}.

    Hanya item dengan price > 0. Dipakai untuk economy_config simulator.
    """
    prices: dict[str, float] = {}
    for row in latest_rows or []:
        name = row.get("item_name")
        price = row.get("price")
        if not name:
            continue
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        if value > 0:
            prices[name] = value
    return prices
