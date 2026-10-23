# services/economy/fairprice_liquidity.py — liquidity view fairprice (High/Medium/Low)

from __future__ import annotations

from .constants import LIQ_DISPLAY_HIGH, LIQ_DISPLAY_MED
from .liquidity import MARGIN_LOW

_LIQ_LABELS = {"High": "🟢 High", "Medium": "🟡 Medium", "Low": "🔴 Low"}


def fp_compute_liquidity_view(liq_data: dict | None, is_producible: bool) -> dict | None:
    """View liquidity (weight, margin, label) dari liq_data.

    Return None kalau producible tapi liq_data invalid (score None) —
    caller (fairprice.py) yang handle early-return, konsisten pola asli.
    Non-producible selalu return view default (tidak None).
    """
    if not is_producible:
        return {
            "weight_tech":     1.0,
            "weight_intr":     0.0,
            "margin_pct":      MARGIN_LOW,
            "liq_score":       None,
            "liq_key":         "N/A",
            "liquidity_label": "⚪ N/A (non-producible)",
        }

    if liq_data is None or liq_data["score"] is None:
        return None

    liq_score = liq_data["score"]
    if liq_score >= LIQ_DISPLAY_HIGH:
        liq_key = "High"
    elif liq_score >= LIQ_DISPLAY_MED:
        liq_key = "Medium"
    else:
        liq_key = "Low"

    return {
        "weight_tech":     liq_data["weight_tech"],
        "weight_intr":     liq_data["weight_intr"],
        "margin_pct":      liq_data["margin_pct"],
        "liq_score":       liq_score,
        "liq_key":         liq_key,
        "liquidity_label": _LIQ_LABELS[liq_key],
    }


def fp_compute_data_confidence(
    liq_data: dict | None,
    is_producible: bool,
    anchor_age_days: int | None,
) -> dict:
    """Data confidence metadata (liquidity basis + anchor age + raw score).

    Producible: baca liq_data + anchor_age_days.
    Non-producible: default statis.
    """
    if is_producible:
        return {
            "liquidity_basis":        liq_data["liquidity_basis"],
            "liquidity_history_days": liq_data["liquidity_history_days"],
            "anchor_age_days":        anchor_age_days,
            "raw_liquidity_score":    liq_data["raw_score"],
        }

    return {
        "liquidity_basis":        "non_producible_static",
        "liquidity_history_days": None,
        "anchor_age_days":        None,
        "raw_liquidity_score":    None,
    }
