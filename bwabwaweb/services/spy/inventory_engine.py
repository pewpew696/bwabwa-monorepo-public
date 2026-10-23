# services/spy/inventory_engine.py — helper murni parse inventory dari tx history
# Diekstrak dari cogs/spy/api/inventory.py::_fetch_inventory_equipment (zero logic change).
# Semua fungsi murni; I/O tetap di pemanggil (method asli).

from __future__ import annotations

import re

# --- helpers ---
_SLOT_KEYWORDS = {
    "weapon": ["sniper", "rifle", "pistol", "shotgun", "launcher", "bow", "sword", "axe", "dagger", "wand", "staff", "gun", "knife", "blade", "mace", "spear", "hammer", "cannon", "club", "bat", "tank", "fighter_jet", "fighterjet", "jet"],
    "helmet": ["helmet", "hat", "cap", "hood", "mask", "crown", "bandana"],
    "chest": ["armor", "vest", "plate", "jacket", "robe", "suit", "coat", "chest", "body", "torso", "mail", "chain", "shell"],
    "gloves": ["gloves", "gauntlet", "mitt", "bracer", "hand"],
    "pants": ["pants", "trousers", "legging", "short", "greaves", "leg"],
    "boots": ["boots", "shoes", "sandal", "walker", "greaves", "foot"],
}

_SUFFIX_RARITY = {"1": "common", "2": "uncommon", "3": "rare", "4": "epic", "5": "legendary", "6": "mythic"}
_WEAPON_RARITY = {
    "knife": "common", "gun": "uncommon", "rifle": "rare",
    "sniper": "epic", "tank": "legendary", "fighter_jet": "mythic", "fighterjet": "mythic",
}
_SCRAP_MAP: dict[int, list[str]] = {
    2: ["common"],
    6: ["uncommon", "common"],
    18: ["rare", "uncommon"],
    54: ["epic", "rare"],
    162: ["legendary", "epic"],
    486: ["mythic", "legendary"],
    1458: ["mythic"],
}

def _slot_from_code(code: str) -> str:
    c = code.lower()
    for slot, kws in _SLOT_KEYWORDS.items():
        if any(k in c for k in kws):
            return slot
    return "unknown"

def _rarity_from_code(code: str, raw_rarity: str | None = None) -> str:
    c = code.lower()
    if c in _WEAPON_RARITY:
        return _WEAPON_RARITY[c]
    m = re.search(r'(\d+)$', code)
    if m:
        return _SUFFIX_RARITY.get(m.group(1), "common")
    if raw_rarity:
        return raw_rarity.lower()
    return "common"

def _norm_skills(skills: dict | None) -> dict:
    if not skills:
        return {}
    return {k: str(v) for k, v in skills.items()}

def _make_item(raw: dict) -> dict:
    code = raw.get("code") or raw.get("name") or "unknown"
    raw_rarity = raw.get("rarity") or raw.get("itemRarity") or raw.get("tier")
    slot = raw.get("slot") or raw.get("itemSlot") or raw.get("category") or _slot_from_code(code)
    skills = _norm_skills(raw.get("skills") or raw.get("stats") or raw.get("attributes"))
    item_id = raw.get("_id") or raw.get("id") or raw.get("itemId")
    rarity = _rarity_from_code(code, raw_rarity)
    return {
        "_id": item_id,
        "code": code,
        "rarity": rarity,
        "slot": slot,
        "skills": skills,
    }

def _remove_item(inv: dict, item: dict, is_dismantle: bool = False) -> tuple[dict | None, str]:
    item_id = item.get("_id")
    code, rarity, skills = item["code"], item.get("rarity", "common"), item.get("skills", {})

    if item_id:
        for slot, daftar in inv.items():
            for i, it in enumerate(daftar):
                if it.get("_id") == item_id:
                    return daftar.pop(i), "id_match"

    if is_dismantle:
        for slot, daftar in inv.items():
            for i, it in enumerate(daftar):
                if it["code"] == code and it["skills"] == skills:
                    return daftar.pop(i), "code_skills_match"

    for slot, daftar in inv.items():
        for i, it in enumerate(daftar):
            if it["code"] == code and it["rarity"] == rarity and it["skills"] == skills:
                return daftar.pop(i), "exact_match"

    for slot, daftar in inv.items():
        for i, it in enumerate(daftar):
            if it["code"] == code and it["rarity"] == rarity:
                return daftar.pop(i), "code_rarity_match"

    for slot, daftar in inv.items():
        for i, it in enumerate(daftar):
            if it["code"] == code:
                return daftar.pop(i), "fifo"

    return None, "not_found"

def _item_power(skills: dict) -> int:
    total = 0
    for v in skills.values():
        try:
            total += int(v)
        except (TypeError, ValueError):
            pass
    return total

def _remove_worst_by_rarity(inv: dict, rarity_target: str) -> dict | None:
    """Hapus 1 item rarity_target yang stats-nya paling rendah."""
    kandidat = []
    for slot, daftar in inv.items():
        for i, it in enumerate(daftar):
            if it["rarity"] == rarity_target:
                kandidat.append((slot, i, it, _item_power(it["skills"])))
    if not kandidat:
        return None
    kandidat.sort(key=lambda x: x[3])
    slot, idx, item, _ = kandidat[0]
    return inv[slot].pop(idx)

