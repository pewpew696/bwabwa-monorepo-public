# tests/test_fairprice_market.py — unit test fp_parse_orderbook + helper spread
"""
Unit test ekshaustif untuk fungsi di services/economy/fairprice_market.py.
Tujuan: nutup blind-spot differential test (kalau tidak ada sampel yang hit
kondisi tertentu, perubahan logic bisa lolos).
"""

from __future__ import annotations

import pytest

from services.economy.fairprice_market import (
    SPREAD_HEALTHY_MAX,
    SPREAD_MODERATE_MAX,
    _fp_spread_label,
    _fp_spread_pct,
    fp_parse_orderbook,
)


# --- fp_parse_orderbook ---

def test_parse_orderbook_none():
    """orderbook None -> semua default, spread None/Unknown."""
    ob = fp_parse_orderbook(None)
    assert ob == {
        "best_bid":     None,
        "best_ask":     None,
        "buy_vol":      0,
        "sell_vol":     0,
        "total_qty":    0,
        "spread_pct":   None,
        "spread_label": "⚪ Unknown",
        "spread_key":   "Unknown",
    }


def test_parse_orderbook_full_healthy():
    """Bid/ask rapat (spread kecil) -> Healthy."""
    ob = fp_parse_orderbook({
        "best_bid": 100.0, "best_ask": 102.0,
        "buy_vol": 100, "sell_vol": 200,
    })
    assert ob["best_bid"] == 100.0
    assert ob["best_ask"] == 102.0
    assert ob["buy_vol"] == 100
    assert ob["sell_vol"] == 200
    assert ob["total_qty"] == 300
    assert ob["spread_pct"] is not None
    assert ob["spread_key"] == "Healthy"


def test_parse_orderbook_moderate():
    """Spread moderate."""
    ob = fp_parse_orderbook({"best_bid": 100.0, "best_ask": 108.0})
    assert ob["spread_key"] == "Moderate"


def test_parse_orderbook_wide():
    """Spread wide (40%)."""
    ob = fp_parse_orderbook({"best_bid": 80.0, "best_ask": 120.0})
    assert ob["spread_key"] == "Wide"


def test_parse_orderbook_missing_volume_defaults():
    """Volume key tidak ada -> default 0, bukan crash."""
    ob = fp_parse_orderbook({"best_bid": 100.0, "best_ask": 102.0})
    assert ob["buy_vol"] == 0
    assert ob["sell_vol"] == 0
    assert ob["total_qty"] == 0


def test_parse_orderbook_only_bid():
    """Cuma bid, tidak ada ask -> spread None."""
    ob = fp_parse_orderbook({"best_bid": 100.0, "buy_vol": 50})
    assert ob["best_bid"] == 100.0
    assert ob["best_ask"] is None
    assert ob["spread_pct"] is None
    assert ob["spread_key"] == "Unknown"


def test_parse_orderbook_only_ask():
    """Cuma ask, tidak ada bid -> spread None."""
    ob = fp_parse_orderbook({"best_ask": 100.0, "sell_vol": 50})
    assert ob["spread_pct"] is None
    assert ob["spread_key"] == "Unknown"


def test_parse_orderbook_empty_dict():
    """Dict kosong -> default semua."""
    ob = fp_parse_orderbook({})
    assert ob["best_bid"] is None
    assert ob["best_ask"] is None
    assert ob["total_qty"] == 0
    assert ob["spread_key"] == "Unknown"


# --- _fp_spread_pct ---

def test_spread_pct_none_bid():
    assert _fp_spread_pct(None, 100.0) is None


def test_spread_pct_none_ask():
    assert _fp_spread_pct(100.0, None) is None


def test_spread_pct_mid_zero():
    """bid=ask=0 -> mid=0 -> return None (hindari div by zero)."""
    assert _fp_spread_pct(0.0, 0.0) is None


def test_spread_pct_mid_negative():
    """Bid/ask negatif -> mid negatif -> None."""
    assert _fp_spread_pct(-10.0, -5.0) is None


def test_spread_pct_normal():
    """Bid 100, ask 110 -> mid 105, spread (10/105)*100 ≈ 9.52%."""
    assert _fp_spread_pct(100.0, 110.0) == pytest.approx(9.523809, rel=1e-5)


def test_spread_pct_zero_spread():
    """Bid == ask -> spread 0%."""
    assert _fp_spread_pct(100.0, 100.0) == 0.0


# --- _fp_spread_label ---

def test_spread_label_none():
    assert _fp_spread_label(None) == ("⚪ Unknown", "Unknown")


@pytest.mark.parametrize("pct,expected_key", [
    (0.0, "Healthy"),
    (4.9, "Healthy"),       # < 5.0
    (5.0, "Moderate"),      # boundary: >= 5.0 masuk Moderate
    (11.9, "Moderate"),
    (12.0, "Moderate"),     # boundary: <= 12.0 masih Moderate
    (12.1, "Wide"),
    (50.0, "Wide"),
])
def test_spread_label_boundaries(pct, expected_key):
    """Boundary exact di SPREAD_HEALTHY_MAX (5.0) dan SPREAD_MODERATE_MAX (12.0)."""
    _, key = _fp_spread_label(pct)
    assert key == expected_key, f"pct={pct} expected={expected_key}, got {key}"


def test_spread_label_constants_values():
    """Konstanta threshold tidak berubah tanpa sengaja."""
    assert SPREAD_HEALTHY_MAX == 5.0
    assert SPREAD_MODERATE_MAX == 12.0
