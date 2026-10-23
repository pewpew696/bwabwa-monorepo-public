# tests/test_fairprice_cost.py — unit test fp_compute_cost_engine
"""
Unit test untuk fp_compute_cost_engine — orkestrasi cost (pp_value + cost_info + bonus).
Sentinel None = producible invalid; non-producible selalu return dict.
"""

from __future__ import annotations

import pytest

from services.economy.fairprice_cost import fp_compute_cost_engine


def _price_cache():
    return {
        "Iron": 100.0, "Wood": 80.0, "Grain": 60.0, "Limestone": 120.0,
        "Petroleum": 90.0, "Lead": 50.0, "Livestock": 200.0, "Fish": 300.0,
        "Mysterious Plant": 500.0,
    }


def _median_bonus_ok(item):
    return (10.0, "median")


def _get_bonus_ok(item):
    return (15.0, "auto")


# --- non-producible ---

def test_cost_engine_nonproducible_default():
    """Non-producible -> dict default, tidak ada kalkulasi."""
    r = fp_compute_cost_engine(
        _price_cache(), "Scraps", False, _median_bonus_ok, _get_bonus_ok,
    )
    assert r == {
        "pp_value":       0.0,
        "cost_info":      None,
        "bonus_best_pct": None,
        "production_cost": None,
        "break_even":     None,
    }


# --- producible valid ---

def test_cost_engine_producible_steel():
    """Steel producible valid -> semua field terisi."""
    r = fp_compute_cost_engine(
        _price_cache(), "Steel", True, _median_bonus_ok, _get_bonus_ok,
    )
    assert r is not None
    assert r["pp_value"] > 0
    assert r["cost_info"] is not None
    assert r["production_cost"] is not None
    assert r["break_even"] == r["production_cost"]
    assert r["bonus_best_pct"] == 15.0


def test_cost_engine_break_even_same_as_production_cost():
    """break_even = production_cost (invariant)."""
    r = fp_compute_cost_engine(
        _price_cache(), "Iron", True, _median_bonus_ok, _get_bonus_ok,
    )
    assert r["break_even"] == r["production_cost"]


# --- producible invalid (sentinel None) ---

def test_cost_engine_pp_value_zero_returns_none():
    """price_cache kosong -> pp_value 0 -> None."""
    r = fp_compute_cost_engine(
        {}, "Steel", True, _median_bonus_ok, _get_bonus_ok,
    )
    assert r is None


def test_cost_engine_item_not_in_chain_returns_none():
    """Item tidak ada di PRODUCTION_CHAIN -> cost_info None -> None."""
    r = fp_compute_cost_engine(
        _price_cache(), "Scraps", True, _median_bonus_ok, _get_bonus_ok,
    )
    assert r is None


def test_cost_engine_input_missing_returns_none():
    """Input produksi tidak ada harga -> input_ok False -> None."""
    cache = _price_cache()
    del cache["Lead"]  # input untuk Ammo
    r = fp_compute_cost_engine(
        cache, "Ammo", True, _median_bonus_ok, _get_bonus_ok,
    )
    assert r is None


# --- passthrough callback ---

def test_cost_engine_calls_median_bonus_callback():
    """Callback get_median_bonus dipanggil dengan item."""
    calls = []
    def spy(item):
        calls.append(item)
        return (10.0, "median")

    fp_compute_cost_engine(_price_cache(), "Iron", True, spy, _get_bonus_ok)
    assert "Iron" in calls


def test_cost_engine_calls_get_bonus_callback():
    """Callback get_bonus dipanggil dengan item."""
    calls = []
    def spy(item):
        calls.append(item)
        return (15.0, "auto")

    fp_compute_cost_engine(_price_cache(), "Iron", True, _median_bonus_ok, spy)
    assert "Iron" in calls


def test_cost_engine_does_not_call_callbacks_when_nonproducible():
    """Non-producible -> callback TIDAK dipanggil (skip cost logic)."""
    calls = []
    def spy_mb(item):
        calls.append(("mb", item))
        return (10.0, "median")
    def spy_b(item):
        calls.append(("b", item))
        return (15.0, "auto")

    fp_compute_cost_engine(_price_cache(), "Scraps", False, spy_mb, spy_b)
    assert calls == []


def test_cost_engine_return_dict_keys_consistent():
    """Return dict punya 5 key konsisten (producible & non)."""
    expected = {"pp_value", "cost_info", "bonus_best_pct", "production_cost", "break_even"}
    r_prod = fp_compute_cost_engine(
        _price_cache(), "Iron", True, _median_bonus_ok, _get_bonus_ok,
    )
    r_non = fp_compute_cost_engine(
        _price_cache(), "Scraps", False, _median_bonus_ok, _get_bonus_ok,
    )
    assert set(r_prod.keys()) == expected
    assert set(r_non.keys()) == expected


# --- nilai absolut (regression guard) ---

def test_cost_engine_steel_absolute_value():
    """Steel: production_cost = (input_cost + pp_cost) / output_mult.

    Fixture: Iron=100, pp_value = (100+80+60+120)/4 = 90
    Chain Steel: input=(Iron,10), pp=10
    -> input_cost = 10 * 100 = 1000
    -> pp_cost = 90 * 10 = 900
    -> output_mult = 1 + 10/100 = 1.1
    -> production_cost = (1000+900) / 1.1 ≈ 1727.27
    """
    r = fp_compute_cost_engine(
        _price_cache(), "Steel", True, _median_bonus_ok, _get_bonus_ok,
    )
    assert r["pp_value"] == pytest.approx(90.0)
    assert r["production_cost"] == pytest.approx((1000.0 + 900.0) / 1.1, rel=1e-5)


def test_cost_engine_iron_absolute_value():
    """Iron raw (no input): production_cost = pp_cost / output_mult.

    pp_value exclude Iron = (80+60+120)/3 = 86.667
    Chain Iron: input=None, pp=1
    -> input_cost = 0
    -> pp_cost = 86.667 * 1 = 86.667
    -> output_mult = 1.1
    -> production_cost ≈ 78.79
    """
    r = fp_compute_cost_engine(
        _price_cache(), "Iron", True, _median_bonus_ok, _get_bonus_ok,
    )
    assert r["pp_value"] == pytest.approx(86.666667, rel=1e-5)
    assert r["production_cost"] == pytest.approx(86.666667 / 1.1, rel=1e-5)
