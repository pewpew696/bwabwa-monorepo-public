# services/economy/items.py — resolver nama item (free function, shared Discord + web)

from __future__ import annotations

from typing import Optional


# Alias input user -> nama canonical (slang umum WarEra).
ITEM_ALIASES: dict[str, str] = {
    "coca":         "Mysterious Plant",
    "coke":         "Mysterious Plant",
    "scrap":        "Scraps",
    "mystplant":    "Mysterious Plant",
    "heavyammo":    "Heavy Ammo",
    "lightammo":    "Light Ammo",
    "woodencase":   "Wooden Case",
}


def _lookup_alias(query: str) -> str | None:
    """Cek alias slang dulu. Return nama canonical kalau ada."""
    q_nospace = query.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for alias, canonical in ITEM_ALIASES.items():
        if alias == q_nospace:
            return canonical
    return None


def resolve_item(cache: dict, query: str) -> Optional[str]:
    """Resolver 3-tahap: exact -> startswith -> substring (spasi diabaikan).

    Tahap startswith penting: tanpa itu "ammo" bisa nyasar ke "Light Ammo"
    tergantung urutan iterasi cache.
    """
    alias = _lookup_alias(query)
    if alias:
        return alias
    q = query.lower()
    q_nospace = q.replace(" ", "")
    # 1. exact ("case1" cocok "Case 1")
    for name in cache:
        if name.lower().replace(" ", "") == q_nospace:
            return name
    # 2. startswith
    for name in cache:
        if name.lower().replace(" ", "").startswith(q_nospace):
            return name
    # 3. substring
    for name in cache:
        if q_nospace in name.lower().replace(" ", ""):
            return name
    return None


# --- helper item ID / label / API key (dipindah dari market/items.py) ---

from .constants import (  # noqa: E402
    ITEM_LABELS,
    API_KEY_TO_ITEM_ID,
    ITEM_ID_TO_API_KEY,
)


def _label(item_id: str) -> str:
    return ITEM_LABELS.get(item_id, item_id.replace("_", " ").title())


def _item_id_from_api_key(key: str) -> str:
    return API_KEY_TO_ITEM_ID.get(key, key)


def _api_key_from_item_id(item_id: str) -> str | None:
    return ITEM_ID_TO_API_KEY.get(item_id)


def _resolve_item_id(query: str) -> str | None:
    alias = _lookup_alias(query)
    if alias:
        alias_id = alias.strip().lower().replace(" ", "_")
        if alias_id in ITEM_LABELS:
            return alias_id
    q = query.strip().lower().replace(" ", "_").replace("-", "_")
    if q in ITEM_LABELS:
        return q

    q_nospace = q.replace("_", "")
    for item_id in ITEM_LABELS:
        if item_id.replace("_", "") == q_nospace:
            return item_id

    q_raw = query.strip().lower()
    for item_id, label in ITEM_LABELS.items():
        if q_raw and q_raw in label.lower():
            return item_id

    return None
