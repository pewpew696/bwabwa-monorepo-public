# tests/test_fairprice_liquidity.py — unit test fp_compute_liquidity_view
"""
Unit test ekshaustif untuk fp_compute_liquidity_view.
Boundary LIQ_DISPLAY_HIGH (0.65) + LIQ_DISPLAY_MED (0.35).
"""

from __future__ import annotations

import pytest

from services.economy.constants import LIQ_DISPLAY_HIGH, LIQ_DISPLAY_MED
from services.economy.fairprice_liquidity import (
    fp_compute_data_confidence,
    fp_compute_liquidity_view,
)
from services.economy.liquidity import MARGIN_LOW


def _liq_data(score):
    return {
        "score":                   score,
        "raw_score":               score,
        "margin_pct":              2.0,
        "weight_tech":             0.7,
        "weight_intr":             0.3,
        "liquidity_basis":         "established",
        "liquidity_history_days":  60,
    }


# --- non-producible ---

def test_nonproducible_returns_default_view():
    """Non-producible selalu return default, liq_data apapun diabaikan."""
    view = fp_compute_liquidity_view(None, is_producible=False)
    assert view == {
        "weight_tech":     1.0,
        "weight_intr":     0.0,
        "margin_pct":      MARGIN_LOW,
        "liq_score":       None,
        "liq_key":         "N/A",
        "liquidity_label": "⚪ N/A (non-producible)",
    }


def test_nonproducible_ignores_liq_data():
    """Non-producible + liq_data valid -> tetap default."""
    view = fp_compute_liquidity_view(_liq_data(0.9), is_producible=False)
    assert view["liq_key"] == "N/A"
    assert view["liq_score"] is None


# --- producible: sentinel None ---

def test_producible_liq_data_none_returns_none():
    """Producible + liq_data None -> None (sentinel)."""
    assert fp_compute_liquidity_view(None, is_producible=True) is None


def test_producible_score_none_returns_none():
    """Producible + score None -> None."""
    data = _liq_data(0.5)
    data["score"] = None
    assert fp_compute_liquidity_view(data, is_producible=True) is None


# --- producible: label boundaries ---

@pytest.mark.parametrize("score,expected_key", [
    (0.0,  "Low"),
    (0.34, "Low"),
    (0.35, "Medium"),   # boundary: >= LIQ_DISPLAY_MED
    (0.64, "Medium"),
    (0.65, "High"),     # boundary: >= LIQ_DISPLAY_HIGH
    (0.99, "High"),
    (1.0,  "High"),
])
def test_liquidity_label_boundaries(score, expected_key):
    view = fp_compute_liquidity_view(_liq_data(score), is_producible=True)
    assert view["liq_key"] == expected_key


def test_liquidity_view_passthrough_values():
    """Nilai weight/margin diteruskan apa adanya dari liq_data."""
    data = _liq_data(0.7)
    data["weight_tech"] = 0.55
    data["weight_intr"] = 0.45
    data["margin_pct"] = 3.2
    view = fp_compute_liquidity_view(data, is_producible=True)
    assert view["weight_tech"] == 0.55
    assert view["weight_intr"] == 0.45
    assert view["margin_pct"] == 3.2
    assert view["liq_score"] == 0.7


def test_liquidity_label_emoji_high():
    view = fp_compute_liquidity_view(_liq_data(0.9), is_producible=True)
    assert view["liquidity_label"] == "🟢 High"


def test_liquidity_label_emoji_medium():
    view = fp_compute_liquidity_view(_liq_data(0.5), is_producible=True)
    assert view["liquidity_label"] == "🟡 Medium"


def test_liquidity_label_emoji_low():
    view = fp_compute_liquidity_view(_liq_data(0.1), is_producible=True)
    assert view["liquidity_label"] == "🔴 Low"


def test_liquidity_constants_values():
    """Konstanta threshold liquidity tidak berubah tanpa sengaja."""
    assert LIQ_DISPLAY_HIGH == 0.65
    assert LIQ_DISPLAY_MED == 0.35


# --- fp_compute_data_confidence ---

def _make_data_conf_liq():
    return {
        "score":                   0.5,
        "raw_score":               0.55,
        "margin_pct":              2.0,
        "weight_tech":             0.5,
        "weight_intr":             0.5,
        "liquidity_basis":         "established",
        "liquidity_history_days":  60,
    }


def test_data_confidence_producible_full():
    """Producible: semua field diambil dari liq_data + anchor_age."""
    r = fp_compute_data_confidence(_make_data_conf_liq(), True, anchor_age_days=15)
    assert r == {
        "liquidity_basis":        "established",
        "liquidity_history_days": 60,
        "anchor_age_days":        15,
        "raw_liquidity_score":    0.55,
    }


def test_data_confidence_producible_anchor_none():
    """Producible + anchor None -> tetap masuk None."""
    r = fp_compute_data_confidence(_make_data_conf_liq(), True, anchor_age_days=None)
    assert r["anchor_age_days"] is None
    assert r["liquidity_basis"] == "established"


def test_data_confidence_nonproducible_static():
    """Non-producible -> default statis, liq_data diabaikan."""
    r = fp_compute_data_confidence(_make_data_conf_liq(), False, anchor_age_days=15)
    assert r == {
        "liquidity_basis":        "non_producible_static",
        "liquidity_history_days": None,
        "anchor_age_days":        None,
        "raw_liquidity_score":    None,
    }


def test_data_confidence_nonproducible_with_none_liq():
    """Non-producible + liq_data None -> tetap default."""
    r = fp_compute_data_confidence(None, False, anchor_age_days=None)
    assert r["liquidity_basis"] == "non_producible_static"


def test_data_confidence_producible_passthrough_basis():
    """liquidity_basis diteruskan apa adanya dari liq_data."""
    liq = _make_data_conf_liq()
    liq["liquidity_basis"] = "provisional"
    r = fp_compute_data_confidence(liq, True, anchor_age_days=5)
    assert r["liquidity_basis"] == "provisional"


def test_data_confidence_return_keys_always_same():
    """Return dict selalu 4 key (producible / non-producible)."""
    expected_keys = {"liquidity_basis", "liquidity_history_days", "anchor_age_days", "raw_liquidity_score"}
    r_prod = fp_compute_data_confidence(_make_data_conf_liq(), True, anchor_age_days=10)
    r_non = fp_compute_data_confidence(None, False, anchor_age_days=None)
    assert set(r_prod.keys()) == expected_keys
    assert set(r_non.keys()) == expected_keys
