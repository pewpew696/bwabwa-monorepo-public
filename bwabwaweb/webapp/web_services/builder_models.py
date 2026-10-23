# builder_models.py
"""Model Pydantic Build Optimizer (tanpa fastapi)."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from simulator.constants import (
    FOOD_ITEMS,
    PRODUCTION_CHAIN,
    RARITY_ORDER,
    SKILL_MAX_LEVEL,
    SKILLS,
    max_sp_at_char_level,
    total_sp_for_allocation,
)
from simulator.economy_skills import ECO_FORMULA_SKILLS
from webapp.web_services.simulator_service import (
    EQUIPMENT_SLOTS_WEB,
    EQUIPMENT_STAT_KEYS,
)


class Mode(str, Enum):
    """Mode optimizer (nama milik owner, bukan Intel).

    BALANCE (Fase 2, satu-satunya yang jalan): metrik ranking = gold_per_k
    TERENDAH, yaitu net cost per 1K damage:
        net_cost = (gear + consumables)
            - (scrap + case + company + work)
        (battle_loot di-skip: belum bisa dipetakan, keputusan owner 2026-10-09)
        gold_per_k = net_cost / (mean_damage / 1000)
    Negatif = profit. Sesuai kalibrasi Fase 1 (rumus net Intel, probe 2026-10-08);
    company & work dari simulator/economy_skills.py (port cogs/economy).

    FARMER (Fase 3, jalan): damage BUKAN alasan utama — objektif =
    loot chance MAKSIMAL, yaitu case_income TERTINGGI (bukan damage).
    Ranking = case_income menurun. Kalkulasi sama seperti Balance
    (Monte Carlo RNG); bedanya hanya metrik ranking di compare store.

    GLASS_CANNON (Fase 4, jalan): objektif = damage burst SETINGGI
    mungkin; gold BUKAN parameter utama tapi gold_per_k tetap jadi
    pertimbangan. Ranking = daily_damage MENURUN, tiebreak gold_per_k
    menaik. Tidak berarti semua gear harus merah.
    """

    BALANCE = "balance"
    FARMER = "farmer"
    GLASS_CANNON = "glass_cannon"


# Batas atas stat Advanced = max range resmi per stat (RARITY_STAT_RANGES).
ADV_STAT_MAX = {
    "weapon_atk": 300,
    "weapon_crit_chance": 50,
    "helmet_crit_dmg": 150,
    "armor": 70,
    "dodge": 60,
    "precision": 60,
}

# Semua key harga yang boleh di-override user (superset statis dari semua
# item yang mungkin dibutuhkan validasi harga DB).
KNOWN_PRICE_KEYS = frozenset(
    ["Case 1", "Case 2", "Scraps", "Steel", "Pill",
     "Light Ammo", "Ammo", "Heavy Ammo"]
    + list(FOOD_ITEMS.keys())
    + list(PRODUCTION_CHAIN.keys())
    + [prod["input"][0] for prod in PRODUCTION_CHAIN.values() if prod.get("input")]
)

_AMMO_ITEM = {"light": "Light Ammo", "ammo": "Ammo", "heavy": "Heavy Ammo"}


def required_market_items(config: "BuildConfig") -> list[str]:
    """Item yang harganya WAJIB ada (DB atau override) untuk build ini.

    Anti-hardcode (keputusan owner 2026-10-09): tidak ada harga tebakan.
    """
    items = ["Case 1", "Case 2", "Scraps", "Steel"]
    if config.ammo_tier in _AMMO_ITEM:
        items.append(_AMMO_ITEM[config.ammo_tier])
    if config.food_type != "none":
        items.append(config.food_type)
    if config.pill == "buff":
        items.append("Pill")
    for c in config.companies:
        items.append(c.production_target)
        prod = PRODUCTION_CHAIN.get(c.production_target) or {}
        if prod.get("input"):
            items.append(prod["input"][0])
    return list(dict.fromkeys(items))


def build_advanced_equipment(config: "BuildConfig") -> dict:
    """Equipment exact user -> format engine {slot: {stats, durability, [value]}}.

    Slot tanpa stat > 0 dilewati (no gear). Durability default 100.
    """
    out: dict = {}
    for slot in EQUIPMENT_SLOTS_WEB:
        stats = {
            k: float(v)
            for k, v in (config.equipment_stats.get(slot) or {}).items()
            if float(v) > 0
        }
        if not stats:
            continue
        entry: dict = {
            "stats": stats,
            "durability": config.equipment_durability.get(slot, 100),
        }
        value = config.gear_values.get(slot)
        if value is not None:
            entry["value"] = float(value)
        out[slot] = entry
    return out


def resolve_market_prices(
    config: "BuildConfig", db_prices: dict | None
) -> tuple[dict, dict]:
    """Harga efektif = DB + override user (override hanya di Advanced).

    Return (harga_efektif, override_terpakai). Tiap item yang dibutuhkan
    harus ada di DB atau override — kalau tidak, ValueError eksplisit.
    """
    overrides = dict(config.price_overrides) if config.detail == "advanced" else {}
    market = {**(db_prices or {}), **overrides}
    needed = required_market_items(config)
    missing = [it for it in needed if it not in market]
    if missing:
        raise ValueError(
            "harga DB tidak tersedia untuk: " + ", ".join(missing)
            + " — coba lagi nanti."
        )
    used = {k: overrides[k] for k in needed if k in overrides}
    return market, used


class CompanyInput(BaseModel):
    """Satu company aktif (Simplified). Bonus = bonus produksi region %."""

    model_config = ConfigDict(extra="forbid")

    ae_level: int = Field(default=1, ge=1, le=7)
    production_target: str = Field(min_length=1)
    bonus_pct: float = Field(default=0.0, ge=0.0)

    @field_validator("production_target")
    @classmethod
    def _check_target(cls, target: str) -> str:
        if target not in PRODUCTION_CHAIN:
            raise ValueError(f"production_target tidak dikenal: {target}")
        return target


class BuildConfig(BaseModel):
    """Satu build. detail=simplified (rarity) atau advanced (stat exact)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Build 1", min_length=1, max_length=40)
    mode: Mode = Mode.BALANCE
    char_level: int = Field(default=50, ge=1, le=50)
    skills: dict[str, int] = Field(default_factory=dict)
    equipment: dict[str, str] = Field(default_factory=dict)
    pill: Literal["buff", "none"] = "buff"
    ammo_tier: Literal["none", "light", "ammo", "heavy"] = "ammo"
    food_type: Literal["Bread", "Steak", "Cooked Fish", "none"] = "Steak"
    battle_bonus_pct: float = Field(default=0.0, ge=0.0, le=135.0)
    rank_bonus_pct: float = Field(default=0.0, ge=0.0, le=37.5)
    window: Literal["8h", "16h", "24h"] = "8h"
    # Skill ekonomi — field sendiri, BUKAN bagian SKILLS (ada di SKILLS_EXCLUDED).
    eco_levels: dict[str, int] = Field(default_factory=dict)
    companies: list[CompanyInput] = Field(default_factory=list, max_length=12)
    wage_net: float = Field(default=0.0, ge=0.0)
    detail: Literal["simplified", "advanced"] = "simplified"
    # Field Advanced — hanya dipakai bila detail == "advanced" (simplified:
    # divalidasi bentuknya tapi diabaikan diam-diam).
    equipment_stats: dict[str, dict[str, float]] = Field(default_factory=dict)
    equipment_durability: dict[str, float] = Field(default_factory=dict)
    gear_values: dict[str, float] = Field(default_factory=dict)
    price_overrides: dict[str, float] = Field(default_factory=dict)

    @field_validator("skills")
    @classmethod
    def _check_skills(cls, skills: dict[str, int]) -> dict[str, int]:
        for key, level in skills.items():
            if key not in SKILLS:
                raise ValueError(f"skill tidak dikenal: {key}")
            if not isinstance(level, int) or not 0 <= level <= SKILL_MAX_LEVEL:
                raise ValueError(f"{key}: level harus 0-{SKILL_MAX_LEVEL}")
        return skills

    @field_validator("equipment")
    @classmethod
    def _check_equipment(cls, equipment: dict[str, str]) -> dict[str, str]:
        for slot, rarity in equipment.items():
            if slot not in EQUIPMENT_SLOTS_WEB:
                raise ValueError(f"slot tidak dikenal: {slot}")
            if rarity not in RARITY_ORDER:
                raise ValueError(f"rarity tidak valid: {rarity}")
        return equipment

    @field_validator("eco_levels")
    @classmethod
    def _check_eco_levels(cls, eco_levels: dict[str, int]) -> dict[str, int]:
        for key, level in eco_levels.items():
            if key not in ECO_FORMULA_SKILLS:
                raise ValueError(f"eco skill tidak dikenal: {key}")
            if not isinstance(level, int) or not 0 <= level <= SKILL_MAX_LEVEL:
                raise ValueError(f"{key}: level harus 0-{SKILL_MAX_LEVEL}")
        return eco_levels

    @field_validator("equipment_stats")
    @classmethod
    def _check_equipment_stats(
        cls, stats: dict[str, dict[str, float]]
    ) -> dict[str, dict[str, float]]:
        for slot, statmap in (stats or {}).items():
            if slot not in EQUIPMENT_SLOTS_WEB:
                raise ValueError(f"slot tidak dikenal: {slot}")
            if not isinstance(statmap, dict):
                raise ValueError(f"{slot}: harus mapping stat")
            allowed = EQUIPMENT_STAT_KEYS[slot]
            for key, value in statmap.items():
                if key not in allowed:
                    raise ValueError(f"{slot}: stat tidak dikenal: {key}")
                v = float(value)
                if not 0 <= v <= ADV_STAT_MAX[key]:
                    raise ValueError(f"{slot}.{key}: harus 0-{ADV_STAT_MAX[key]}")
        return stats

    @field_validator("equipment_durability")
    @classmethod
    def _check_equipment_durability(cls, durs: dict[str, float]) -> dict[str, float]:
        for slot, pct in (durs or {}).items():
            if slot not in EQUIPMENT_SLOTS_WEB:
                raise ValueError(f"slot tidak dikenal: {slot}")
            if not 1 <= float(pct) <= 100:
                raise ValueError(f"{slot}: durability harus 1-100")
        return durs

    @field_validator("gear_values")
    @classmethod
    def _check_gear_values(cls, values: dict[str, float]) -> dict[str, float]:
        for slot, value in (values or {}).items():
            if slot not in EQUIPMENT_SLOTS_WEB:
                raise ValueError(f"slot tidak dikenal: {slot}")
            if float(value) < 0:
                raise ValueError(f"{slot}: gear value tidak boleh negatif")
        return values

    @field_validator("price_overrides")
    @classmethod
    def _check_price_overrides(cls, overrides: dict[str, float]) -> dict[str, float]:
        for key, price in (overrides or {}).items():
            if key not in KNOWN_PRICE_KEYS:
                raise ValueError(f"harga override tidak dikenal: {key}")
            if float(price) <= 0:
                raise ValueError(f"{key}: harga override harus > 0")
        return overrides

    @model_validator(mode="after")
    def _check_sp_budget(self) -> "BuildConfig":
        for key, level in self.skills.items():
            if level > 0 and self.char_level < SKILLS[key]["unlock"]:
                raise ValueError(f"{key} butuh character level >={SKILLS[key]['unlock']}")
        used = total_sp_for_allocation({k: v for k, v in self.skills.items() if v > 0})
        budget = max_sp_at_char_level(self.char_level)
        if used > budget:
            raise ValueError(f"SP melebihi budget: pakai {used}, tersedia {budget}")
        # Slot company: base 2 + skill companies (tiap level +1 slot).
        max_companies = 2 + self.skills.get("companies", 0)
        if len(self.companies) > max_companies:
            raise ValueError(
                f"company melebihi slot: {len(self.companies)} > {max_companies} "
                "(naikkan skill companies)"
            )
        return self


@dataclass(frozen=True)
class BuildResult:
    name: str
    mode: str
    window: str
    breakdown: dict
    detail: str = "simplified"
    overrides_used: dict = field(default_factory=dict)


def apply_pins(skills: dict[str, int], pins: dict[str, int]) -> dict[str, int]:
    """Pin override nilai form — skill yang di-pin selalu pakai level pin."""
    merged = dict(skills)
    merged.update(pins or {})
    return merged
