# services/economy/fairprice_market.py — helper spread market

from __future__ import annotations

from typing import Optional

# --- constants / thresholds ---

SPREAD_HEALTHY_MAX  = 5.0
SPREAD_MODERATE_MAX = 12.0


def _fp_spread_pct(best_bid: Optional[float], best_ask: Optional[float]) -> Optional[float]:
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        return None
    return (best_ask - best_bid) / mid * 100


def _fp_spread_label(spread_pct: Optional[float]) -> tuple[str, str]:
    if spread_pct is None:
        return "⚪ Unknown", "Unknown"
    if spread_pct < SPREAD_HEALTHY_MAX:
        return "🟢 Healthy", "Healthy"
    if spread_pct <= SPREAD_MODERATE_MAX:
        return "🟡 Moderate", "Moderate"
    return "🔴 Wide", "Wide"


def fp_parse_orderbook(orderbook: dict | None) -> dict:
    """Parse orderbook -> dict bid/ask/volume + spread.

    None aman (return nilai default). Sensitivitas "orderbook error" sudah
    di-handle di caller (dikonversi ke None sebelum dipanggil).
    """
    best_bid  = orderbook.get("best_bid") if orderbook else None
    best_ask  = orderbook.get("best_ask") if orderbook else None
    buy_vol   = orderbook.get("buy_vol", 0) if orderbook else 0
    sell_vol  = orderbook.get("sell_vol", 0) if orderbook else 0
    total_qty = buy_vol + sell_vol

    spread_pct               = _fp_spread_pct(best_bid, best_ask)
    spread_label, spread_key = _fp_spread_label(spread_pct)

    return {
        "best_bid":     best_bid,
        "best_ask":     best_ask,
        "buy_vol":      buy_vol,
        "sell_vol":     sell_vol,
        "total_qty":    total_qty,
        "spread_pct":   spread_pct,
        "spread_label": spread_label,
        "spread_key":   spread_key,
    }
