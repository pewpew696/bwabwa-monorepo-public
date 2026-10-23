# builder_forms.py
"""Parsing form HTML -> BuildConfig (tanpa fastapi).

Dipisah dari routes/builder.py supaya file route tetap ramping.
Semua batas angka/enum dicek Pydantic di BuildConfig; di sini hanya
konversi string form -> tipe Python.
"""
from pydantic import ValidationError

from simulator.constants import SKILLS
from webapp.core.errors import ValidationAppError
from webapp.web_services.builder_models import BuildConfig, apply_pins
from webapp.web_services.simulator_service import (
    EQUIPMENT_SLOTS_WEB,
    EQUIPMENT_STAT_KEYS,
)

BUILD_NAME_MAX = 40
MAX_COMPANY_ROWS = 12
MAX_PRICE_OVERRIDE_ROWS = 10
ECO_SKILL_KEYS = ("energy", "production", "entrepreneurship")


def _to_int(raw, default: int = 0) -> int:
    try:
        return int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _to_float(raw, default: float = 0.0) -> float:
    try:
        return float(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _opt_float(form, name: str, default: float = 0.0):
    """Float opsional dari form; None bila input kosong."""
    raw = form.get(name)
    return _to_float(raw, default) if raw not in (None, "") else None


def _parse_mode(raw) -> str:
    """Mode dari form; ketiga mode sudah jalan."""
    mode = str(raw or "balance").strip()
    if mode not in ("balance", "farmer", "glass_cannon"):
        raise ValidationAppError("mode belum tersedia")
    return mode


def _parse_detail(raw) -> str:
    """Detail dari form: simplified (rarity) atau advanced (stat exact)."""
    detail = str(raw or "simplified").strip()
    if detail not in ("simplified", "advanced"):
        raise ValidationAppError("detail tidak valid")
    return detail


def _parse_pinned_levels(form, existing: dict[str, int]) -> dict[str, int]:
    """Pin baru dari form. Checkbox centang + nilai ada -> set level itu;
    checkbox centang + nilai tidak ada (input disabled) -> pin lama dipertahankan;
    tidak dicentang -> pin dilepas."""
    pins: dict[str, int] = {}
    for key in SKILLS:
        if not form.get(f"pin_{key}"):
            continue
        raw = form.get(f"skill_{key}")
        if raw not in (None, ""):
            pins[key] = _to_int(raw)
        elif key in existing:
            pins[key] = existing[key]
    return pins


def _parse_advanced(form) -> dict:
    """Field Advanced dari form; input kosong = tidak diisi.

    Nama field: adv_{slot}_{stat}, adv_{slot}_dur, adv_{slot}_value,
    price_ov_{idx}_item + price_ov_{idx}_price.
    """
    equipment_stats: dict[str, dict[str, float]] = {}
    equipment_durability: dict[str, float] = {}
    gear_values: dict[str, float] = {}
    for slot in EQUIPMENT_SLOTS_WEB:
        stats: dict[str, float] = {}
        for stat_key in EQUIPMENT_STAT_KEYS[slot]:
            value = _to_float(form.get(f"adv_{slot}_{stat_key}"))
            if value > 0:
                stats[stat_key] = value
        if stats:
            equipment_stats[slot] = stats
        dur = _opt_float(form, f"adv_{slot}_dur", 100)
        if dur is not None:
            equipment_durability[slot] = dur
        val = _opt_float(form, f"adv_{slot}_value")
        if val is not None:
            gear_values[slot] = val
    price_overrides: dict[str, float] = {}
    for idx in range(MAX_PRICE_OVERRIDE_ROWS):
        item = str(form.get(f"price_ov_{idx}_item") or "").strip()
        price = _opt_float(form, f"price_ov_{idx}_price")
        if item and price:
            price_overrides[item] = price
    return {
        "equipment_stats": equipment_stats,
        "equipment_durability": equipment_durability,
        "gear_values": gear_values,
        "price_overrides": price_overrides,
    }


def _parse_config(form, pins: dict[str, int] | None = None) -> BuildConfig:
    """Form -> BuildConfig. Batas angka/enum dicek Pydantic di service.

    pins (dari session): override nilai form — skill yang di-pin selalu
    pakai level pin-nya, bukan nilai form yang mungkin basi.
    """
    skills = apply_pins(
        {key: _to_int(form.get(f"skill_{key}")) for key in SKILLS},
        pins,
    )
    equipment: dict[str, str] = {}
    for slot in EQUIPMENT_SLOTS_WEB:
        rarity = str(form.get(f"equip_{slot}_rarity") or "").strip()
        if rarity:
            equipment[slot] = rarity
    name = str(form.get("build_name") or "").strip()[:BUILD_NAME_MAX] or "Build 1"
    eco_levels = {key: _to_int(form.get(f"eco_{key}")) for key in ECO_SKILL_KEYS}
    companies: list[dict] = []
    for idx in range(MAX_COMPANY_ROWS):
        target = str(form.get(f"company_{idx}_target") or "").strip()
        if not target:
            continue
        companies.append({
            "ae_level": _to_int(form.get(f"company_{idx}_ae"), 1),
            "production_target": target,
            "bonus_pct": _to_float(form.get(f"company_{idx}_bonus")),
        })
    payload = {
        "name": name,
        "mode": _parse_mode(form.get("mode")),
        "detail": _parse_detail(form.get("detail")),
        "char_level": _to_int(form.get("char_level"), 50),
        "skills": skills,
        "equipment": equipment,
        "pill": str(form.get("pill") or "buff").strip(),
        "ammo_tier": str(form.get("ammo_tier") or "ammo").strip(),
        "food_type": str(form.get("food_type") or "Steak").strip(),
        "battle_bonus_pct": _to_float(form.get("battle_bonus_pct")),
        "rank_bonus_pct": _to_float(form.get("rank_bonus_pct")),
        "window": str(form.get("window") or "8h").strip(),
        "eco_levels": eco_levels,
        "companies": companies,
        "wage_net": _to_float(form.get("wage_net")),
        **_parse_advanced(form),
    }
    try:
        return BuildConfig(**payload)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise ValidationAppError(f"input build tidak valid: {first.get('msg', 'cek form')}")
