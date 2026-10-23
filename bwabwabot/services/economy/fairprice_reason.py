# services/economy/fairprice_reason.py — helper confidence & reason engine

from __future__ import annotations

# --- reason constants ---

HOLD_LOW_CONFIDENCE     = "HOLD_LOW_CONFIDENCE"
HOLD_FAIR_RANGE         = "HOLD_FAIR_RANGE"
HOLD_INSUFFICIENT_EDGE  = "HOLD_INSUFFICIENT_EDGE"
MISMATCH_FAIR_BUY       = "MISMATCH_FAIR_BUY"
MISMATCH_OVERVALUED_BUY = "MISMATCH_OVERVALUED_BUY"
BUY_UNDERVALUED         = "BUY_UNDERVALUED"
SELL_OVERVALUED         = "SELL_OVERVALUED"


def _fp_market_confidence(spread_key: str, history_len: int, has_bid: bool, has_ask: bool) -> float:
    spread_score  = {"Wide": 0, "Unknown": 0, "Moderate": 15, "Healthy": 30}.get(spread_key, 0)
    history_score = 0 if history_len < 2 else (15 if history_len < 7 else 30)
    bidask_score  = 40 if (has_bid and has_ask) else (20 if (has_bid or has_ask) else 0)
    return min(spread_score + history_score + bidask_score, 100)


def _fp_reason_key(recommendation: str, valuation_key: str, low_confidence: bool) -> str:
    """Matriks 3x3 (valuasi x rekomendasi) -> kategori reason."""
    if recommendation == "HOLD":
        if low_confidence:
            return HOLD_LOW_CONFIDENCE
        if valuation_key == "Fair":
            return HOLD_FAIR_RANGE
        return HOLD_INSUFFICIENT_EDGE
    if recommendation == "BUY":
        if valuation_key == "Overvalued":
            return MISMATCH_OVERVALUED_BUY
        if valuation_key == "Fair":
            return MISMATCH_FAIR_BUY
        return BUY_UNDERVALUED
    return SELL_OVERVALUED


def _fp_model_confidence(cost_info: dict, pp_value: float) -> float:
    score = 25.0
    if cost_info["bonus_source"] != "none":
        score += 25.0
    if pp_value > 0:
        score += 25.0
    if cost_info["input_ok"]:
        score += 25.0
    return score


def fp_compute_reasons(
    reason_key: str,
    valuation_key: str,
    valuation_pct: float,
    spread_key: str,
    is_producible: bool,
    liq_key: str,
    liq_score: float | None,
    orderbook_failed: bool,
    trend_opposes: bool,
    trend_key: str,
) -> list[str]:
    """Susun list alasan tekstual dari state valuation + market + risk.

    Urutan & isi dipertahankan persis dari _fp_analyze (tidak diubah).
    """
    reasons: list[str] = [reason_key]
    if reason_key == HOLD_LOW_CONFIDENCE:
        reasons.append("⚠️ Data quality rendah — confidence di bawah ambang aman")
    if reason_key == MISMATCH_FAIR_BUY:
        reasons.append("⚠️ BUY inside Fair Range — good buy threshold (cost basis) hit first")
    if reason_key == MISMATCH_OVERVALUED_BUY:
        reasons.append("⚠️ BUY despite Overvalued — good buy is based on production cost, not fair range")
    if reason_key == HOLD_INSUFFICIENT_EDGE:
        reasons.append("Price is outside Fair Range, but hasn't hit the good buy/sell threshold yet")
    if valuation_key == "Undervalued":
        reasons.append(f"{abs(valuation_pct):.1f}% below Fair Value")
    elif valuation_key == "Overvalued":
        reasons.append(f"{abs(valuation_pct):.1f}% above Fair Value")
    else:
        reasons.append("Price is still within Fair Range")
    reasons.append(f"Spread {spread_key.lower()}")
    if is_producible:
        reasons.append(f"Liquidity {liq_key.lower()} (score {liq_score:.2f})")
    else:
        reasons.append("Liquidity N/A (non-producible)")
    if orderbook_failed:
        reasons.append("⚠️ Orderbook fetch failed — bid/ask data unavailable")
    if trend_opposes:
        reasons.append(f"⚠️ {trend_key} trend conflicts with valuation")
    else:
        reasons.append(f"Trend {trend_key.lower()}")

    return reasons
