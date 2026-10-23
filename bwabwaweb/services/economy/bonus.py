# services/economy/bonus.py — kalkulasi bonus party/country/deposit

from __future__ import annotations

from datetime import datetime

from .constants import AMMO_OR_CONSTRUCTION_IDS, FOOD_OR_BUFF_IDS
from .items import _item_id_from_api_key


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _party_industrialism(party: dict | None) -> int:
    if not party:
        return 0
    raw = party.get("ethics", {}).get("industrialism", 0)
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        val = 0
    return int(_clamp(val, -2, 2))


def _party_specialization_bonus(item_id: str, party: dict | None) -> float:
    industrialism = _party_industrialism(party)
    if item_id not in AMMO_OR_CONSTRUCTION_IDS:
        return 0
    if industrialism >= 2:
        return 30
    if industrialism >= 1:
        return 10
    return 0


def _party_deposit_bonus(item_id: str, party: dict | None) -> float:
    industrialism = _party_industrialism(party)
    if industrialism <= -2 and item_id in FOOD_OR_BUFF_IDS:
        return 30
    if industrialism <= -1 and item_id in FOOD_OR_BUFF_IDS:
        return 10
    return 0


def _should_apply_country_bonus(party: dict | None) -> bool:
    return _party_industrialism(party) > -2


def _should_apply_deposit_bonus(item_id: str, party: dict | None) -> bool:
    industrialism = _party_industrialism(party)
    if industrialism >= 2:
        return False
    if industrialism <= -1:
        return item_id in FOOD_OR_BUFF_IDS
    return True


def _country_bonus_pct(country: dict | None, item_id: str, party: dict | None) -> float:
    if not country:
        return 0
    specialized = country.get("specializedItem")
    specialized_id = _item_id_from_api_key(specialized) if specialized else None
    if specialized_id != item_id:
        return 0
    if not _should_apply_country_bonus(party):
        return 0
    base = (
        country.get("strategicResources", {}).get("bonuses", {}).get("productionPercent")
        or country.get("rankings", {}).get("countryProductionBonus", {}).get("value", 0)
    )
    try:
        base = max(0.0, float(base or 0))
    except (TypeError, ValueError):
        base = 0.0
    return round(base + _party_specialization_bonus(item_id, party), 6)


def _deposit_bonus_pct(region: dict | None, item_id: str, party: dict | None, now: datetime) -> float:
    if not region:
        return 0
    deposit = region.get("deposit")
    if not deposit:
        return 0
    deposit_type = deposit.get("type")
    deposit_id = _item_id_from_api_key(deposit_type) if deposit_type else None
    if deposit_id != item_id:
        return 0
    if not _should_apply_deposit_bonus(item_id, party):
        return 0
    starts_at = deposit.get("startsAt")
    ends_at   = deposit.get("endsAt")
    try:
        if starts_at and now < datetime.fromisoformat(str(starts_at).replace("Z", "+00:00")):
            return 0
        if ends_at and now > datetime.fromisoformat(str(ends_at).replace("Z", "+00:00")):
            return 0
    except (ValueError, AttributeError, TypeError):
        pass
    try:
        base = max(0.0, float(deposit.get("bonusPercent") or 0))
    except (TypeError, ValueError):
        base = 0.0
    return round(base + _party_deposit_bonus(item_id, party), 6)
