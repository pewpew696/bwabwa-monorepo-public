# builder_import.py
"""Player import Build Optimizer: username WarEra -> auto-fill form.

Orkestrasi async (aiohttp session per request, pola player_service) +
mapping murni (dict mentah API -> dict siap isi form). Tanpa fastapi di sini.
"""
import asyncio
import logging

from services.spy.api_client import (
    get_current_equipment,
    get_wage_info,
)
from services.spy.company_bonus import resolve_companies_with_bonus
from services.spy.search import find_player_exact
from services.spy.utils import classify_stat_range
from simulator.constants import PRODUCTION_CHAIN, SKILL_MAX_LEVEL
from simulator.economy_skills import ECO_FORMULA_SKILLS

log = logging.getLogger("bwabwabot.builder_import")

# builder key -> key skills di user_lite (baca empiris di services/spy/report.py).
SKILL_IMPORT_MAP = {
    "attack": "attack",
    "precision": "precision",
    "crit_chance": "criticalChance",
    "crit_damage": "criticalDamages",
    "armor": "armor",
    "dodge": "dodge",
    "health": "health",
    "hunger": "hunger",
    "loot_chance": "lootChance",
    "companies": "companies",
}
ECO_IMPORT_KEYS = tuple(ECO_FORMULA_SKILLS)  # energy, production, entrepreneurship

# slot builder -> (kategori RARITY_STAT_RANGES, sumber nilai).
# weapon/helmet/gloves/boots: bonus gear ada di user_lite.skills (pola
# _build_gear di player_service); chest/pants: dari fetchCurrentEquipment.
_EQUIP_SOURCES = {
    "weapon": ("weapon_atk", ("lite", "attack", "weapon")),
    "helmet": ("helmet_crit_dmg", ("lite", "criticalDamages", "equipment")),
    "gloves": ("precision", ("lite", "precision", "equipment")),
    "boots": ("dodge", ("lite", "dodge", "equipment")),
    "chest": ("armor", ("equipment", "chest", "armor")),
    "pants": ("armor", ("equipment", "pants", "armor")),
}

# Label emoji classifier -> nama rarity builder (simulator RARITY_ORDER).
_EMOJI_RARITY = {
    "White": "Putih", "Green": "Hijau", "Blue": "Biru",
    "Purple": "Ungu", "Orange": "Oren", "Red": "Merah",
}

MAX_IMPORT_COMPANIES = 12


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _clamp_level(value) -> int:
    """Level skill API -> 0..SKILL_MAX_LEVEL (prestige di atasnya dipotong)."""
    try:
        level = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(SKILL_MAX_LEVEL, level))


def map_char_level(user_lite: dict) -> int:
    """Character level dari user_lite.leveling; fallback 50."""
    leveling = (user_lite or {}).get("leveling") or {}
    try:
        level = int(leveling.get("level") or 50)
    except (TypeError, ValueError):
        level = 50
    return max(1, min(50, level))


def map_skills(user_lite: dict) -> tuple[dict[str, int], dict[str, int]]:
    """Skills combat + eco dari user_lite.skills (level per skill)."""
    skills = (user_lite or {}).get("skills") or {}
    combat = {
        builder_key: _clamp_level((skills.get(api_key) or {}).get("level"))
        for builder_key, api_key in SKILL_IMPORT_MAP.items()
    }
    eco = {
        key: _clamp_level((skills.get(key) or {}).get("level"))
        for key in ECO_IMPORT_KEYS
    }
    return combat, eco


def _classify_to_builder(category: str, value: float) -> str | None:
    """Nilai stat mentah -> nama rarity builder; None kalau tak dikenali."""
    label = classify_stat_range(category, value)
    if not label or label.startswith("?"):
        return None
    return _EMOJI_RARITY.get(label.split()[-1])  # "Purple" -> "Ungu"


def map_equipment(user_lite: dict, equipment: dict | None) -> dict[str, str]:
    """Rarity per slot untuk Simplified. Slot kosong/tak dikenal dilewati."""
    skills = (user_lite or {}).get("skills") or {}
    equipment = equipment or {}
    out: dict[str, str] = {}
    for slot, (category, source) in _EQUIP_SOURCES.items():
        kind = source[0]
        value = 0.0
        if kind == "lite":
            _, api_key, field = source
            value = _safe_float((skills.get(api_key) or {}).get(field))
        else:
            _, eq_slot, field = source
            item = equipment.get(eq_slot) or {}
            value = _safe_float((item.get("skills") or {}).get(field))
        if value <= 0 and equipment.get(slot):
            # Fallback: stat terbesar dari item mentah di slot itu.
            item_skills = (equipment.get(slot) or {}).get("skills") or {}
            value = max([_safe_float(v) for v in item_skills.values()] + [0.0])
        rarity = _classify_to_builder(category, value) if value > 0 else None
        if rarity:
            out[slot] = rarity
    return out


def map_companies(resolved: list[dict]) -> list[dict]:
    """Company ter-resolve (bonus_pct riil dari API) -> baris form builder.
    Item tak dikenal (known=False) dilewati."""
    out: list[dict] = []
    for c in resolved or []:
        if len(out) >= MAX_IMPORT_COMPANIES:
            break
        if not c.get("known"):
            continue
        label = c.get("item_label") or ""
        if label not in PRODUCTION_CHAIN:
            continue
        try:
            ae = int(c.get("ae_level") or 1)
        except (TypeError, ValueError):
            ae = 1
        out.append({
            "ae_level": max(1, min(7, ae)),
            "production_target": label,
            "bonus_pct": round(_safe_float(c.get("bonus_pct")), 6),
        })
    return out


def map_wage(wage_data: dict | None) -> float:
    """gold_per_pp dari transaksi wage terakhir; 0 kalau tidak ada."""
    return _safe_float((wage_data or {}).get("gold_per_pp"))


def build_import_result(username, char_level, skills, eco_levels,
                         equipment, companies, wage_net) -> dict:
    """Rakit dict siap isi form. Tidak ada raw API response di sini."""
    return {
        "username": username,
        "char_level": char_level,
        "skills": skills,
        "eco_levels": eco_levels,
        "equipment": equipment,
        "companies": companies,
        "wage_net": round(wage_net, 6),
    }


async def import_player(username: str) -> dict:
    """Username WarEra -> dict auto-fill builder. ValueError bila gagal."""
    name = (username or "").strip()
    if not name:
        raise ValueError("username kosong")
    import aiohttp  # lazy: hanya dipakai saat request nyata, bukan di test
    # find_player_exact sudah mengembalikan user_lite (bukan cuma ID).
    async with aiohttp.ClientSession() as session:
        user_lite, suggestions = await find_player_exact(session, name)
        if not user_lite:
            hint = f" Mungkin maksud: {', '.join(suggestions)}" if suggestions else ""
            raise ValueError("pemain tidak ditemukan")
        user_id = user_lite.get("_id") or ""
        equipment, company_rows, wage_data = await asyncio.gather(
            get_current_equipment(session, user_id),
            resolve_companies_with_bonus(session, user_id),
            get_wage_info(session, user_id),
        )
    skills, eco = map_skills(user_lite)
    return build_import_result(
        username=user_lite.get("username") or name,
        char_level=map_char_level(user_lite),
        skills=skills,
        eco_levels=eco,
        equipment=map_equipment(user_lite, equipment),
        companies=map_companies(company_rows),
        wage_net=map_wage(wage_data),
    )
