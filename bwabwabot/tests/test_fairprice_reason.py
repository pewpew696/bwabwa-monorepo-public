# tests/test_fairprice_reason.py — unit test fp_compute_reasons
"""
Unit test untuk fp_compute_reasons. Fokus: urutan + isi list reasons
harus stabil terhadap semua kombinasi reason_key/valuation_key.
"""

from __future__ import annotations

import pytest

from services.economy.fairprice_reason import (
    HOLD_INSUFFICIENT_EDGE,
    HOLD_LOW_CONFIDENCE,
    MISMATCH_FAIR_BUY,
    MISMATCH_OVERVALUED_BUY,
    fp_compute_reasons,
)


def _base_args(**overrides):
    base = {
        "reason_key":       "BUY_UNDERVALUED",
        "valuation_key":    "Undervalued",
        "valuation_pct":    -10.0,
        "spread_key":       "Healthy",
        "is_producible":    True,
        "liq_key":          "High",
        "liq_score":        0.8,
        "orderbook_failed": False,
        "trend_opposes":    False,
        "trend_key":        "Sideways",
    }
    base.update(overrides)
    return base


def test_reasons_first_element_is_reason_key():
    """Elemen pertama selalu reason_key."""
    r = fp_compute_reasons(**_base_args())
    assert r[0] == "BUY_UNDERVALUED"


def test_reasons_hold_low_confidence_appends_warning():
    r = fp_compute_reasons(**_base_args(reason_key=HOLD_LOW_CONFIDENCE))
    assert any("Data quality rendah" in x for x in r)


def test_reasons_mismatch_fair_buy_appends_warning():
    r = fp_compute_reasons(**_base_args(reason_key=MISMATCH_FAIR_BUY))
    assert any("BUY inside Fair Range" in x for x in r)


def test_reasons_mismatch_overvalued_buy_appends_warning():
    r = fp_compute_reasons(**_base_args(reason_key=MISMATCH_OVERVALUED_BUY))
    assert any("BUY despite Overvalued" in x for x in r)


def test_reasons_hold_insufficient_edge_appends_warning():
    r = fp_compute_reasons(**_base_args(reason_key=HOLD_INSUFFICIENT_EDGE))
    assert any("hasn't hit the good buy/sell" in x for x in r)


def test_reasons_undervalued_message():
    r = fp_compute_reasons(**_base_args(valuation_key="Undervalued", valuation_pct=-5.3))
    assert any("5.3% below Fair Value" in x for x in r)


def test_reasons_overvalued_message():
    r = fp_compute_reasons(**_base_args(valuation_key="Overvalued", valuation_pct=12.4))
    assert any("12.4% above Fair Value" in x for x in r)


def test_reasons_fair_message():
    r = fp_compute_reasons(**_base_args(valuation_key="Fair", valuation_pct=0.0))
    assert any("still within Fair Range" in x for x in r)


def test_reasons_spread_lowercase():
    r = fp_compute_reasons(**_base_args(spread_key="Wide"))
    assert "Spread wide" in r


def test_reasons_liquidity_producible():
    r = fp_compute_reasons(**_base_args(is_producible=True, liq_key="Medium", liq_score=0.5))
    assert any("Liquidity medium (score 0.50)" in x for x in r)


def test_reasons_liquidity_nonproducible():
    r = fp_compute_reasons(**_base_args(is_producible=False, liq_key="N/A", liq_score=None))
    assert any("Liquidity N/A (non-producible)" in x for x in r)


def test_reasons_orderbook_failed_warning():
    r = fp_compute_reasons(**_base_args(orderbook_failed=True))
    assert any("Orderbook fetch failed" in x for x in r)


def test_reasons_no_orderbook_warning_when_false():
    r = fp_compute_reasons(**_base_args(orderbook_failed=False))
    assert not any("Orderbook fetch failed" in x for x in r)


def test_reasons_trend_opposes_warning():
    r = fp_compute_reasons(**_base_args(trend_opposes=True, trend_key="Bearish"))
    assert any("Bearish trend conflicts" in x for x in r)


def test_reasons_trend_normal():
    r = fp_compute_reasons(**_base_args(trend_opposes=False, trend_key="Bullish"))
    assert any("Trend bullish" in x for x in r)


def test_reasons_order_stable():
    """Urutan elemen harus konsisten (regression guard)."""
    r = fp_compute_reasons(**_base_args())
    # [reason_key, valuation, spread, liquidity, trend] — 5 elemen
    assert len(r) == 5
    assert r[0] == "BUY_UNDERVALUED"
    assert "below Fair Value" in r[1]
    assert r[2].startswith("Spread")
    assert r[3].startswith("Liquidity")
    assert r[4].startswith("Trend")


def test_reasons_all_warnings_combined():
    """Semua kondisi warning aktif -> semua muncul, urutan tetap."""
    r = fp_compute_reasons(**_base_args(
        reason_key=HOLD_LOW_CONFIDENCE,
        orderbook_failed=True,
        trend_opposes=True,
    ))
    assert any("Data quality rendah" in x for x in r)
    assert any("Orderbook fetch failed" in x for x in r)
    assert any("trend conflicts" in x for x in r)
