# services/economy/fairprice_display.py — helper tampilan nama item

from __future__ import annotations

ITEM_SHORT_NAMES: dict[str, str] = {
    "Mysterious Plant": "Myst. Plant",
}
NAME_COL_WIDTH = 13


def _short_name(name: str) -> str:
    short = ITEM_SHORT_NAMES.get(name, name)
    if len(short) > NAME_COL_WIDTH:
        short = short[: NAME_COL_WIDTH - 1] + "…"
    return short
