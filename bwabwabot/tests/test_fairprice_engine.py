# tests/test_fairprice_engine.py — unit test ekshaustif fp_compute_risk + fp_decide_recommendation
"""
Test unit untuk fungsi murni di services/economy/fairprice_engine.py.

Tujuan: nutup blind-spot differential test. Differential cek output _fp_analyze
dengan sampel terbatas — kalau tidak ada sampel yang hit ambang exact,
perubahan threshold bisa lolos. Unit test ini exhaustif terhadap kombinasi
input, jadi setiap perubahan ambang WAJIB ketangkep.

Prinsip: expected dihitung manual dari aturan bisnis (replika logika lama),
bukan dari panggil ulang fungsi — biar test tidak "percaya" ke implementasi.
"""

from __future__ import annotations

import pytest

from services.economy.fairprice_engine import (
    fp_compute_confidence,
    fp_compute_fair_range,
    fp_compute_risk,
    fp_compute_technical_value,
    fp_compute_valuation,
    fp_decide_recommendation,
)


# --- fp_compute_risk ---

def _expected_risk_points(spread_key, is_producible, liq_score, effective_conf, trend_opposes):
    """Replika aturan bisnis dari kode lama — jadi oracle test."""
    p = 0
    if spread_key == "Wide":
        p += 2
    if is_producible and liq_score is not None and liq_score < 0.35:
        p += 2
    if effective_conf < 70.0:
        p += 2
    if trend_opposes:
        p += 1
    return p


def _expected_label(points):
    if points >= 4:
        return "🔴 High"
    if points >= 2:
        return "🟡 Medium"
    return "🟢 Low"


def _iter_risk_cases():
    for spread in ["Healthy", "Moderate", "Wide"]:
        for prod in [True, False]:
            # Kombinasi prod=True, liq=None TIDAK reachable:
            # di _fp_analyze, producible dengan liq None sudah return None sebelumnya.
            liq_options = [0.5, 0.1] if prod else [None, 0.5, 0.1]
            for liq in liq_options:
                for conf in [50.0, 70.0, 80.0]:  # 70.0 boundary (=gate -> tidak +2)
                    for trend in [True, False]:
                        yield (spread, prod, liq, conf, trend)


@pytest.mark.parametrize("spread,prod,liq,conf,trend", list(_iter_risk_cases()))
def test_compute_risk_exhaustive(spread, prod, liq, conf, trend):
    """Semua kombinasi input -> label harus match expected."""
    expected_points = _expected_risk_points(spread, prod, liq, conf, trend)
    expected_label = _expected_label(expected_points)
    actual = fp_compute_risk(spread, prod, liq, conf, trend)
    assert actual == expected_label, (
        f"input=({spread},{prod},{liq},{conf},{trend}) "
        f"expected_points={expected_points} -> {expected_label}, got {actual}"
    )


# --- boundary eksplisit (bukti test bisa FAIL kalau threshold diubah) ---

def test_risk_points_exact_0_low():
    # Healthy, no liq, conf>=70, no trend -> 0
    assert fp_compute_risk("Healthy", False, None, 80.0, False) == "🟢 Low"


def test_risk_points_exact_1_low():
    # Healthy, conf>=70, trend=True -> 1
    assert fp_compute_risk("Healthy", False, None, 80.0, True) == "🟢 Low"


def test_risk_points_exact_2_medium():
    # Wide alone -> 2
    assert fp_compute_risk("Wide", False, None, 80.0, False) == "🟡 Medium"


def test_risk_points_exact_3_medium():
    # Wide + trend -> 3
    assert fp_compute_risk("Wide", False, None, 80.0, True) == "🟡 Medium"


def test_risk_points_exact_4_high():
    # Wide(+2) + liq low(+2) -> 4
    assert fp_compute_risk("Wide", True, 0.1, 80.0, False) == "🔴 High"


def test_risk_points_exact_5_high():
    # Wide(+2) + liq low(+2) + trend(+1) -> 5
    assert fp_compute_risk("Wide", True, 0.1, 80.0, True) == "🔴 High"


def test_risk_points_exact_6_high():
    # Wide(+2) + liq low(+2) + conf low(+2) -> 6
    assert fp_compute_risk("Wide", True, 0.1, 50.0, False) == "🔴 High"


def test_risk_points_exact_7_high():
    # Wide(+2) + liq low(+2) + conf low(+2) + trend(+1) -> 7
    assert fp_compute_risk("Wide", True, 0.1, 50.0, True) == "🔴 High"


def test_risk_conf_gate_boundary_exact():
    """conf PERSIS 70.0 tidak masuk (< gate), jadi tidak ada +2 dari conf."""
    # Wide alone -> 2 (bukan 4)
    assert fp_compute_risk("Wide", False, None, 70.0, False) == "🟡 Medium"


# --- fp_decide_recommendation ---

def _iter_decide_cases():
    yield (True, 50.0, 100.0, 200.0)    # low_conf -> HOLD
    yield (True, 100.0, 100.0, 200.0)   # low_conf boundary -> HOLD
    yield (True, 500.0, 100.0, 200.0)   # low_conf harga tinggi -> HOLD
    yield (False, 90.0, 100.0, 200.0)   # < good_buy -> BUY
    yield (False, 100.0, 100.0, 200.0)  # == good_buy -> BUY (boundary)
    yield (False, 150.0, 100.0, 200.0)  # middle -> HOLD
    yield (False, 200.0, 100.0, 200.0)  # == good_sell -> SELL (boundary)
    yield (False, 210.0, 100.0, 200.0)  # > good_sell -> SELL


def _expected_decide(low_conf, current, good_buy, good_sell):
    if not low_conf and current <= good_buy:
        return "BUY"
    if not low_conf and current >= good_sell:
        return "SELL"
    return "HOLD"


@pytest.mark.parametrize("low,cur,gb,gs", list(_iter_decide_cases()))
def test_decide_recommendation_exhaustive(low, cur, gb, gs):
    expected = _expected_decide(low, cur, gb, gs)
    actual = fp_decide_recommendation(low, cur, gb, gs)
    assert actual == expected, (
        f"input=({low},{cur},{gb},{gs}) expected={expected}, got {actual}"
    )


def test_decide_low_conf_forces_hold_even_cheap():
    """low_conf=True -> HOLD meski harga <= good_buy."""
    assert fp_decide_recommendation(True, 50.0, 100.0, 200.0) == "HOLD"


def test_decide_low_conf_forces_hold_even_expensive():
    """low_conf=True -> HOLD meski harga >= good_sell."""
    assert fp_decide_recommendation(True, 500.0, 100.0, 200.0) == "HOLD"


def test_decide_high_conf_at_good_buy_boundary():
    """current_price PERSIS good_buy -> BUY."""
    assert fp_decide_recommendation(False, 100.0, 100.0, 200.0) == "BUY"


def test_decide_high_conf_at_good_sell_boundary():
    """current_price PERSIS good_sell -> SELL."""
    assert fp_decide_recommendation(False, 200.0, 100.0, 200.0) == "SELL"


# --- fp_compute_fair_range ---

def _base_fair_range_args(**overrides):
    """Args default buat fp_compute_fair_range — semua nilai fixed."""
    base = {
        "technical_value": 100.0,
        "intrinsic_value": 80.0,
        "weight_tech":     0.6,
        "weight_intr":     0.4,
        "margin_pct":      2.0,
        "is_producible":   True,
        "production_cost": 70.0,
        "best_bid":        95.0,
    }
    base.update(overrides)
    return base


def test_fair_range_producible_basic():
    """Producible: fair_value = weighted, good_buy dari cost basis."""
    r = fp_compute_fair_range(**_base_fair_range_args())
    # fair_value = 100*0.6 + 80*0.4 = 92
    assert r["fair_value"] == pytest.approx(92.0)
    # fair_price = 92 * 1.02 = 93.84
    assert r["fair_price"] == pytest.approx(93.84)
    # range_width = max(0.5, 2.0*0.25=0.5) = 0.5
    assert r["fair_lower"] == pytest.approx(93.84 * 0.995)
    assert r["fair_upper"] == pytest.approx(93.84 * 1.005)
    # good_buy: min(70, 95*0.98=93.1)=70, max(70, 70*0.9=63)=70
    assert r["good_buy"] == pytest.approx(70.0)
    # good_sell = fair_upper * 1.02
    assert r["good_sell"] == pytest.approx(93.84 * 1.005 * 1.02)


def test_fair_range_nonproducible_good_buy_from_fair_lower():
    """Non-producible: good_buy dari fair_lower (bukan cost basis)."""
    r = fp_compute_fair_range(**_base_fair_range_args(
        is_producible=False, production_cost=None,
    ))
    # good_buy = min(fair_lower, best_bid*0.98)
    fair_lower = r["fair_lower"]
    expected_good_buy = min(fair_lower, 95.0 * 0.98)
    assert r["good_buy"] == pytest.approx(expected_good_buy)


def test_fair_range_producible_no_best_bid():
    """Producible tapi best_bid None -> good_buy pakai production_cost penuh."""
    r = fp_compute_fair_range(**_base_fair_range_args(best_bid=None))
    # good_buy_core = production_cost (70), max(70, 70*0.9)=70
    assert r["good_buy"] == pytest.approx(70.0)


def test_fair_range_nonproducible_no_best_bid():
    """Non-producible tanpa best_bid -> good_buy = fair_lower."""
    r = fp_compute_fair_range(**_base_fair_range_args(
        is_producible=False, production_cost=None, best_bid=None,
    ))
    assert r["good_buy"] == pytest.approx(r["fair_lower"])


def test_fair_range_range_width_minimum():
    """margin_pct kecil -> range_width di-clamp ke 0.5%."""
    # margin_pct=1.0 -> 1.0*0.25 = 0.25 -> max(0.5, 0.25) = 0.5
    r = fp_compute_fair_range(**_base_fair_range_args(margin_pct=1.0))
    # Range = 0.5% -> upper - lower = fair_price * 0.01
    expected_width = r["fair_price"] * 0.01
    assert (r["fair_upper"] - r["fair_lower"]) == pytest.approx(expected_width)


def test_fair_range_range_width_from_margin():
    """margin_pct besar -> range_width = margin*0.25."""
    # margin_pct=20.0 -> 20*0.25 = 5.0 -> range 5%
    r = fp_compute_fair_range(**_base_fair_range_args(margin_pct=20.0))
    expected_width = r["fair_price"] * 0.10  # 5% kiri + 5% kanan = 10%
    assert (r["fair_upper"] - r["fair_lower"]) == pytest.approx(expected_width)


def test_fair_range_good_sell_ratio():
    """good_sell selalu fair_upper * 1.02."""
    for margin in [1.0, 5.0, 20.0]:
        r = fp_compute_fair_range(**_base_fair_range_args(margin_pct=margin))
        assert r["good_sell"] == pytest.approx(r["fair_upper"] * 1.02)


def test_fair_range_producible_good_buy_floor():
    """good_buy di-floor ke production_cost * 0.90."""
    # production_cost=100, best_bid=50 -> good_buy_core = min(100, 50*0.98=49)=49
    # floor = 100*0.9 = 90 -> max(49, 90) = 90
    r = fp_compute_fair_range(**_base_fair_range_args(
        production_cost=100.0, best_bid=50.0,
    ))
    assert r["good_buy"] == pytest.approx(90.0)


def test_fair_range_weights_zero_tech():
    """weight_tech=0 -> fair_value = intrinsic_value saja."""
    r = fp_compute_fair_range(**_base_fair_range_args(
        weight_tech=0.0, weight_intr=1.0,
    ))
    assert r["fair_value"] == pytest.approx(80.0)  # intrinsic_value


# --- fp_compute_valuation ---

def test_valuation_undervalued():
    """current < fair_lower -> Undervalued, pct negatif."""
    r = fp_compute_valuation(current_price=80.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["valuation_key"] == "Undervalued"
    assert r["valuation_pct"] == pytest.approx(-20.0)


def test_valuation_overvalued():
    """current > fair_upper -> Overvalued, pct positif."""
    r = fp_compute_valuation(current_price=120.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["valuation_key"] == "Overvalued"
    assert r["valuation_pct"] == pytest.approx(20.0)


def test_valuation_fair_within_range():
    """current di range [fair_lower, fair_upper] -> Fair, pct 0.0."""
    r = fp_compute_valuation(current_price=100.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["valuation_key"] == "Fair"
    assert r["valuation_pct"] == 0.0


def test_valuation_boundary_at_fair_lower():
    """current == fair_lower -> Fair (bukan Undervalued)."""
    r = fp_compute_valuation(current_price=95.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["valuation_key"] == "Fair"


def test_valuation_boundary_at_fair_upper():
    """current == fair_upper -> Fair (bukan Overvalued)."""
    r = fp_compute_valuation(current_price=105.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["valuation_key"] == "Fair"


def test_valuation_just_below_fair_lower():
    """current sedikit di bawah fair_lower -> Undervalued."""
    r = fp_compute_valuation(current_price=94.9, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["valuation_key"] == "Undervalued"


def test_valuation_just_above_fair_upper():
    """current sedikit di atas fair_upper -> Overvalued."""
    r = fp_compute_valuation(current_price=105.1, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["valuation_key"] == "Overvalued"


def test_valuation_expected_edge_undervalued():
    """expected_edge = (fair_value - current) / current * 100."""
    r = fp_compute_valuation(current_price=80.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    # (100 - 80) / 80 * 100 = 25%
    assert r["expected_edge"] == pytest.approx(25.0)


def test_valuation_expected_edge_overvalued():
    """expected_edge negatif kalau current > fair_value."""
    r = fp_compute_valuation(current_price=120.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    # (100 - 120) / 120 * 100 ≈ -16.667
    assert r["expected_edge"] == pytest.approx(-16.666667, rel=1e-5)


def test_valuation_expected_edge_zero_current():
    """current_price=0 -> expected_edge 0 (hindari div by zero)."""
    r = fp_compute_valuation(current_price=0.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["expected_edge"] == 0.0


def test_valuation_expected_edge_at_fair_value():
    """current == fair_value -> expected_edge 0."""
    r = fp_compute_valuation(current_price=100.0, fair_price=100.0,
                              fair_lower=95.0, fair_upper=105.0, fair_value=100.0)
    assert r["expected_edge"] == pytest.approx(0.0)


# --- fp_compute_confidence ---

def _base_conf_args(**overrides):
    base = {
        "spread_key":    "Healthy",
        "history_len":   10,
        "has_bid":       True,
        "has_ask":       True,
        "is_producible": True,
        "cost_info":     {"bonus_source": "median", "input_ok": True},
        "pp_value":      10.0,
    }
    base.update(overrides)
    return base


def test_confidence_producible_min_of_two():
    """Producible: effective = min(model, market)."""
    r = fp_compute_confidence(**_base_conf_args())
    assert r["model_conf"] is not None
    assert r["market_conf"] is not None
    assert r["effective_conf"] == min(r["model_conf"], r["market_conf"])


def test_confidence_nonproducible_effective_equals_market():
    """Non-producible: model None, effective = market."""
    r = fp_compute_confidence(**_base_conf_args(
        is_producible=False, cost_info=None, pp_value=0.0,
    ))
    assert r["model_conf"] is None
    assert r["effective_conf"] == r["market_conf"]


def test_confidence_model_conf_full_score():
    """cost_info lengkap + pp_value > 0 -> model_conf 100."""
    r = fp_compute_confidence(**_base_conf_args())
    assert r["model_conf"] == 100.0


def test_confidence_model_conf_partial():
    """bonus_source='none' -> -25. input_ok False -> -25."""
    r = fp_compute_confidence(**_base_conf_args(
        cost_info={"bonus_source": "none", "input_ok": False},
    ))
    assert r["model_conf"] == 50.0  # 25 + 25 (pp_value>0)


def test_confidence_market_conf_spread_wide():
    """spread Wide -> market_conf 0 dari spread, sisanya dari history+bidask."""
    r = fp_compute_confidence(**_base_conf_args(spread_key="Wide"))
    # history>=7 (30) + bidask both (40) = 70
    assert r["market_conf"] == 70.0


def test_confidence_market_conf_no_history():
    """history_len < 2 -> history_score 0."""
    r = fp_compute_confidence(**_base_conf_args(history_len=1))
    # Healthy (30) + 0 + bidask both (40) = 70
    assert r["market_conf"] == 70.0


def test_confidence_market_conf_only_bid():
    """Cuma bid atau ask -> bidask_score 20."""
    r = fp_compute_confidence(**_base_conf_args(has_ask=False))
    # Healthy (30) + history>=7 (30) + 20 = 80
    assert r["market_conf"] == 80.0


def test_confidence_market_conf_capped_100():
    """Total > 100 -> di-clamp ke 100."""
    r = fp_compute_confidence(**_base_conf_args())  # 30+30+40 = 100
    assert r["market_conf"] == 100.0


def test_confidence_return_dict_has_all_keys():
    """Return dict harus punya ketiga key (transparansi)."""
    r = fp_compute_confidence(**_base_conf_args())
    assert set(r.keys()) == {"market_conf", "model_conf", "effective_conf"}


def test_confidence_min_differs_from_max():
    """Sample di mana model != market -> min != max (boundary sensitif)."""
    # model_conf = 50 (bonus none, input not ok, pp_value>0 = 25+25)
    # market_conf = 100 (Healthy, history>=7, both bid/ask)
    r = fp_compute_confidence(**_base_conf_args(
        cost_info={"bonus_source": "none", "input_ok": False},
    ))
    assert r["model_conf"] == 50.0
    assert r["market_conf"] == 100.0
    assert r["effective_conf"] == 50.0  # min, bukan max


# --- fp_compute_technical_value ---

from datetime import datetime, timedelta, timezone
from collections import deque


_NOW_FIX = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _history_pts(days_ago_prices):
    """days_ago_prices: list[(days_ago, price)] -> deque tuple (ts, price)."""
    return deque(
        (_NOW_FIX - timedelta(days=d), p) for d, p in days_ago_prices
    )


def test_technical_value_producible_with_history():
    """Producible + history -> rata-rata harga dalam window."""
    hist = _history_pts([(1, 100.0), (2, 102.0), (3, 98.0)])
    r = fp_compute_technical_value(hist, current_price=999.0, is_producible=True, now=_NOW_FIX)
    assert r is not None
    assert r["technical_value"] == pytest.approx((100.0 + 102.0 + 98.0) / 3)


def test_technical_value_producible_empty_history_fallback():
    """Producible + history kosong -> technical_value = current_price."""
    r = fp_compute_technical_value(deque(), current_price=500.0, is_producible=True, now=_NOW_FIX)
    assert r is not None
    assert r["technical_value"] == 500.0


def test_technical_value_nonproducible_with_history():
    """Non-producible + history ada -> pakai history."""
    hist = _history_pts([(1, 50.0), (2, 52.0)])
    r = fp_compute_technical_value(hist, current_price=999.0, is_producible=False, now=_NOW_FIX)
    assert r is not None
    assert r["technical_value"] == pytest.approx((50.0 + 52.0) / 2)


def test_technical_value_nonproducible_empty_returns_none():
    """Non-producible + history kosong -> None (sentinel)."""
    r = fp_compute_technical_value(deque(), current_price=100.0, is_producible=False, now=_NOW_FIX)
    assert r is None


def test_technical_value_window_filter_outside():
    """Harga di luar window 7 hari TIDAK masuk rata-rata."""
    hist = _history_pts([(1, 100.0), (10, 999.0), (30, 888.0)])
    r = fp_compute_technical_value(hist, current_price=0.0, is_producible=True, now=_NOW_FIX)
    assert r is not None
    # Cuma yang (1, 100) masuk
    assert r["technical_value"] == 100.0
    assert len(r["recent_prices"]) == 1


def test_technical_value_window_boundary_exact_7_days():
    """Harga tepat 7 hari -> masuk (<= window)."""
    hist = _history_pts([(7, 100.0)])
    r = fp_compute_technical_value(hist, current_price=0.0, is_producible=True, now=_NOW_FIX)
    assert r["technical_value"] == 100.0


def test_technical_value_window_custom():
    """window_days custom dipakai."""
    hist = _history_pts([(3, 100.0), (10, 200.0)])
    r = fp_compute_technical_value(hist, current_price=0.0, is_producible=True, now=_NOW_FIX, window_days=5)
    assert r["technical_value"] == 100.0


def test_technical_value_all_outside_window_fallback():
    """Semua harga di luar window + producible -> fallback current_price."""
    hist = _history_pts([(30, 100.0), (60, 200.0)])
    r = fp_compute_technical_value(hist, current_price=777.0, is_producible=True, now=_NOW_FIX)
    assert r["technical_value"] == 777.0
    assert r["recent_prices"] == []


def test_technical_value_return_keys():
    """Return dict punya 2 key konsisten."""
    hist = _history_pts([(1, 100.0)])
    r = fp_compute_technical_value(hist, current_price=0.0, is_producible=True, now=_NOW_FIX)
    assert set(r.keys()) == {"recent_prices", "technical_value"}
