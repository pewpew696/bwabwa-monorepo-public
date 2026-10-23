# services/economy/fairprice_engine.py — kalkulasi murni engine fairprice (risk + decision)

from __future__ import annotations

from .constants import CONFIDENCE_GATE, LIQ_DISPLAY_MED
from .fairprice_reason import _fp_market_confidence, _fp_model_confidence


def fp_compute_risk(
    spread_key: str,
    is_producible: bool,
    liq_score: float | None,
    effective_conf: float,
    trend_opposes: bool,
) -> str:
    """Label risk dari kombinasi spread, liquidity, confidence, dan trend.

    Aturan poin (dari kode lama, tidak diubah):
    - spread "Wide": +2
    - producible & liquidity di bawah medium: +2
    - confidence di bawah gate: +2
    - trend berlawanan valuasi: +1
    Total >=4 High, >=2 Medium, sisanya Low.
    """
    risk_points = 0
    if spread_key == "Wide":
        risk_points += 2
    if is_producible and liq_score < LIQ_DISPLAY_MED:
        risk_points += 2
    if effective_conf < CONFIDENCE_GATE:
        risk_points += 2
    if trend_opposes:
        risk_points += 1

    if risk_points >= 4:
        return "🔴 High"
    elif risk_points >= 2:
        return "🟡 Medium"
    else:
        return "🟢 Low"


def fp_decide_recommendation(
    low_confidence: bool,
    current_price: float,
    good_buy: float,
    good_sell: float,
) -> str:
    """BUY kalau harga <= good_buy, SELL kalau >= good_sell, else HOLD.

    Low confidence memaksa HOLD (data kualitas rendah, tidak layak rekomendasi).
    """
    if not low_confidence and current_price <= good_buy:
        return "BUY"
    elif not low_confidence and current_price >= good_sell:
        return "SELL"
    else:
        return "HOLD"


def fp_compute_fair_range(
    technical_value: float,
    intrinsic_value: float,
    weight_tech: float,
    weight_intr: float,
    margin_pct: float,
    is_producible: bool,
    production_cost: float | None,
    best_bid: float | None,
) -> dict:
    """Fair value/price/range + good buy/sell.

    Aturan (tidak diubah dari kode lama):
    - fair_value = bobot technical vs intrinsic
    - fair_price = fair_value + margin
    - range_width_pct = max(0.5, margin_pct * 0.25)
    - good_buy: producible pakai cost basis, non-producible pakai fair_lower
    - good_sell = fair_upper * 1.02
    """
    fair_value = (technical_value * weight_tech) + (intrinsic_value * weight_intr)
    fair_price = fair_value * (1 + margin_pct / 100)

    range_width_pct = max(0.5, margin_pct * 0.25)
    fair_lower = fair_price * (1 - range_width_pct / 100)
    fair_upper = fair_price * (1 + range_width_pct / 100)

    if is_producible:
        good_buy_core = min(production_cost, best_bid * 0.98) if best_bid else production_cost
        good_buy = max(good_buy_core, production_cost * 0.90)
    else:
        good_buy = min(fair_lower, best_bid * 0.98) if best_bid else fair_lower
    good_sell = fair_upper * 1.02

    return {
        "fair_value": fair_value,
        "fair_price": fair_price,
        "fair_lower": fair_lower,
        "fair_upper": fair_upper,
        "good_buy":   good_buy,
        "good_sell":  good_sell,
    }


def fp_compute_valuation(
    current_price: float,
    fair_price: float,
    fair_lower: float,
    fair_upper: float,
    fair_value: float,
) -> dict:
    """Valuation key/pct + expected_edge dari posisi harga vs fair range.

    Aturan (tidak diubah):
    - current < fair_lower -> Undervalued (pct negatif)
    - current > fair_upper -> Overvalued (pct positif)
    - else -> Fair (pct 0.0)
    - expected_edge: (fair_value - current) / current * 100, 0 kalau current falsy
    """
    if current_price < fair_lower:
        valuation_pct = (current_price - fair_price) / fair_price * 100
        valuation_key = "Undervalued"
    elif current_price > fair_upper:
        valuation_pct = (current_price - fair_price) / fair_price * 100
        valuation_key = "Overvalued"
    else:
        valuation_pct = 0.0
        valuation_key = "Fair"

    expected_edge = (fair_value - current_price) / current_price * 100 if current_price else 0.0

    return {
        "valuation_pct": valuation_pct,
        "valuation_key": valuation_key,
        "expected_edge": expected_edge,
    }


def fp_compute_confidence(
    spread_key: str,
    history_len: int,
    has_bid: bool,
    has_ask: bool,
    is_producible: bool,
    cost_info: dict | None,
    pp_value: float,
) -> dict:
    """Confidence komposit: market + model + effective.

    - market_conf dari _fp_market_confidence (spread, history, bid/ask)
    - model_conf dari _fp_model_confidence (cost_info, pp_value) — producible only
    - effective_conf = min(model, market) kalau producible, else market
    """
    market_conf = _fp_market_confidence(spread_key, history_len, has_bid, has_ask)

    if is_producible:
        model_conf = _fp_model_confidence(cost_info, pp_value)
        effective_conf = min(model_conf, market_conf)
    else:
        model_conf = None
        effective_conf = market_conf

    return {
        "market_conf":    market_conf,
        "model_conf":     model_conf,
        "effective_conf": effective_conf,
    }



def fp_compute_technical_value(
    history,
    current_price: float,
    is_producible: bool,
    now,
    window_days: int = 7,
) -> dict | None:
    """Technical value dari rata-rata harga `window_days` terakhir.

    Return None kalau non-producible DAN tidak ada harga terbaru di window
    (caller early-return, konsisten pola sentinel).
    Producible selalu return dict (fallback current_price kalau kosong).
    """
    recent_prices = [p for ts, p in history if (now - ts).total_seconds() / 86400 <= window_days]

    if not is_producible and not recent_prices:
        return None

    if recent_prices:
        technical_value = sum(recent_prices) / len(recent_prices)
    else:
        technical_value = current_price

    return {
        "recent_prices":   recent_prices,
        "technical_value": technical_value,
    }
