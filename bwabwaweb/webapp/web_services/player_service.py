"""Logika Intel player: port dari web_api/search_routes.py tanpa cog.

Semua network call pakai aiohttp.ClientSession baru per request (bukan session
bot). Fungsi murni dari services/spy/ dipakai apa adanya.
"""
import time
from dataclasses import dataclass

import aiohttp

from services.spy.api_client import (
    get_current_equipment,
    get_owned_companies,
    get_wage_info,
)
from services.spy.report import build_report_data
from services.spy.resolve import resolve_country_name, resolve_mu_name
from services.spy.search import find_player_exact
from services.spy.utils import classify_stat_range, not_found_msg
from webapp.core.errors import NotFoundError

CACHE_TTL_SECONDS = 300.0
_cache: dict = {}

BASE_STATS_KEY_MAP = {
    "attack": "attack", "precision": "precision", "crit_chance": "critChance",
    "crit_damage": "critDamage", "armor": "armor", "dodge": "dodge",
    "hp": "hp", "hunger": "hunger", "loot": "loot", "company": "company",
    "energy": "energy", "production": "production", "management": "management",
    "entrepreneurship": "entrepreneurship",
}
TBS_KEY_MAP = {
    "attack": "attack", "precision": "precision", "crit_chance": "critChance",
    "crit_damage": "critDamage", "armor": "armor", "dodge": "dodge",
}


@dataclass(frozen=True)
class PlayerReport:
    user_id: str
    avatar_url: str
    username: str
    level: str
    location: str
    mu: str
    mil_rank: str
    last_seen: str
    build: str
    status: str
    buff_debuff: str
    base_stats: dict
    tbs: dict
    weekly_dmg: float
    total_dmg: float
    gear: dict
    companies: list[dict]
    wage: dict | None


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _build_gear(data: dict, current_equipment: dict | None) -> dict:
    skills = data.get("skills", {})
    attack_obj = skills.get("attack", {}) or {}
    crit_d_obj = skills.get("criticalDamages", {}) or {}
    armor_obj = skills.get("armor", {}) or {}
    dodge_obj = skills.get("dodge", {}) or {}
    prec_obj = skills.get("precision", {}) or {}

    wp_atk = _safe_float(attack_obj.get("weapon"))
    eq_crit_d = _safe_float(crit_d_obj.get("equipment"))
    eq_prec = _safe_float(prec_obj.get("equipment"))
    eq_dodge = _safe_float(dodge_obj.get("equipment"))
    eq_armor = _safe_float(armor_obj.get("equipment"))

    gear = {
        "weapon": {"rarity": classify_stat_range("weapon_atk", wp_atk), "stat": f"Attack +{wp_atk:.0f}"},
        "helmet": {"rarity": classify_stat_range("helmet_crit_dmg", eq_crit_d), "stat": f"Crit Dmg +{eq_crit_d:.0f}%"},
    }

    chest_item = (current_equipment or {}).get("chest") or {}
    pants_item = (current_equipment or {}).get("pants") or {}
    if chest_item:
        chest_armor = _safe_float((chest_item.get("skills") or {}).get("armor"))
        gear["chest"] = {"rarity": classify_stat_range("armor", chest_armor), "stat": f"Armor +{chest_armor:.0f}"}
    if pants_item:
        pants_armor = _safe_float((pants_item.get("skills") or {}).get("armor"))
        gear["pants"] = {"rarity": classify_stat_range("armor", pants_armor), "stat": f"Armor +{pants_armor:.0f}"}
    if not chest_item and not pants_item:
        gear["armor"] = {"rarity": classify_stat_range("armor", eq_armor), "stat": f"Armor +{eq_armor:.0f}"}

    gear["gloves"] = {"rarity": classify_stat_range("precision", eq_prec), "stat": f"Precision +{eq_prec:.0f}"}
    gear["boots"] = {"rarity": classify_stat_range("dodge", eq_dodge), "stat": f"Dodge +{eq_dodge:.0f}"}
    return gear


def _build_companies(company_rows: list[dict]) -> list[dict]:
    companies = []
    for row in company_rows:
        companies.append({
            "name": row.get("name") or "?",
            "ae": int(row.get("ae_level") or 0),
            "item": row.get("item_code") or "?",
            "region_id": row.get("region_id") or "?",
        })
    return companies


class PlayerService:
    async def get_player(self, raw_name: str) -> PlayerReport:
        cache_key = (raw_name or "").strip().lower()
        now_mono = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and (now_mono - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        async with aiohttp.ClientSession() as session:
            data, suggestions = await find_player_exact(session, raw_name)
            if not data:
                raise NotFoundError(not_found_msg("Player", raw_name, suggestions))

            user_id = data.get("_id") or ""
            mu_name = await resolve_mu_name(session, data.get("mu"))
            country_name = await resolve_country_name(session, data.get("country"))
            current_equipment = await get_current_equipment(session, user_id) if user_id else None
            company_rows = await get_owned_companies(session, user_id) if user_id else []
            wage_data = await get_wage_info(session, user_id) if user_id else None

        report = build_report_data(data, mu_name, country_name)
        base_stats = {
            BASE_STATS_KEY_MAP[k]: v
            for k, v in report["base_stats"].items()
            if k in BASE_STATS_KEY_MAP
        }
        tbs = {
            TBS_KEY_MAP[k]: v
            for k, v in report["tbs"].items()
            if k in TBS_KEY_MAP
        }
        rankings = data.get("rankings", {}) or {}
        weekly_dmg = _safe_float((rankings.get("weeklyUserDamages") or {}).get("value"))
        total_dmg = _safe_float((rankings.get("userDamages") or {}).get("value"))

        report_obj = PlayerReport(
            user_id=user_id,
            avatar_url=data.get("avatarUrl", ""),
            username=report["usn"],
            level=report["level"],
            location=report["location"],
            mu=report["mu"],
            mil_rank=report["mil_rank"],
            last_seen=report["last_seen"],
            build=report["build"],
            status=report["status"],
            buff_debuff=report["buff_debuff"],
            base_stats=base_stats,
            tbs=tbs,
            weekly_dmg=weekly_dmg,
            total_dmg=total_dmg,
            gear=_build_gear(data, current_equipment),
            companies=_build_companies(company_rows),
            wage=wage_data,
        )
        _cache[cache_key] = (time.monotonic(), report_obj)
        return report_obj
