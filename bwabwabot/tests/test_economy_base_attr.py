# tests/test_economy_base_attr.py — differential test descriptor _BotAttr
"""Cek 14 property _X -> self.bot.<attr>, termasuk lazy-init + nama beda.
Test negatif: descriptor salah mapping -> FAIL.
"""
from __future__ import annotations

import pytest

from cogs.economy.base import EconomyBase, _BotAttr


class _FakeBot:
    pass


def _make():
    obj = EconomyBase.__new__(EconomyBase)
    obj.bot = _FakeBot()
    return obj


# --- direct access (7) ---

def test_direct_attrs():
    obj = _make()
    obj.bot._session = "S"
    obj.bot._price_cache = {"a": 1}
    obj.bot._volume_cache = {"v": 1}
    obj.bot._price_history = {"h": 1}
    obj.bot._auto_bonus_cache = {"b": 1}
    obj.bot._manual_overrides = {"m": 1}
    obj.bot._username_cache = {"u": 1}
    assert obj._session == "S"
    assert obj._price_cache == {"a": 1}
    assert obj._volume_cache == {"v": 1}
    assert obj._price_history == {"h": 1}
    assert obj._auto_bonus_cache == {"b": 1}
    assert obj._manual_overrides == {"m": 1}
    assert obj._username_cache == {"u": 1}


def test_direct_attrs_identity():
    """Harus return object yang sama, bukan copy."""
    obj = _make()
    d = {"x": 1}
    obj.bot._price_cache = d
    assert obj._price_cache is d


# --- lazy-init (nama sama, 4) ---

def test_lazy_same_name():
    obj = _make()
    assert obj._median_bonus_cache == {}
    assert obj._country_tax_cache == {}
    assert obj._liquidity_score_cache == {}
    assert obj._liquidity_anchor_meta == {}
    # persist
    assert obj._median_bonus_cache is obj.bot._median_bonus_cache


def test_lazy_not_overwrite_existing():
    obj = _make()
    obj.bot._country_tax_cache = {"ID": 10}
    assert obj._country_tax_cache == {"ID": 10}


# --- lazy-init nama beda (2) ---

def test_bonus_breakdown_maps_to_different_attr():
    obj = _make()
    assert obj._bonus_breakdown == {}
    assert hasattr(obj.bot, "_bonus_breakdown_cache")
    assert not hasattr(obj.bot, "_bonus_breakdown") or obj.bot._bonus_breakdown is None


def test_bonus_deposit_ends_maps_to_different_attr():
    obj = _make()
    assert obj._bonus_deposit_ends == {}
    assert hasattr(obj.bot, "_bonus_deposit_ends_cache")


# --- cache harian dengan setter (3) ---

def test_liquidity_score_cache_setter():
    obj = _make()
    obj._liquidity_score_cache = {"Iron": {"score": 1.0}}
    assert obj.bot._liquidity_score_cache == {"Iron": {"score": 1.0}}
    assert obj._liquidity_score_cache == {"Iron": {"score": 1.0}}


def test_liquidity_anchor_meta_setter():
    obj = _make()
    obj._liquidity_anchor_meta = {"calibrated_at": "2026-01-01"}
    assert obj.bot._liquidity_anchor_meta == {"calibrated_at": "2026-01-01"}


def test_price_extremes_cache_setter():
    obj = _make()
    obj._price_extremes_cache = {"Iron": {"high": 100}}
    assert obj.bot._price_extremes_cache == {"Iron": {"high": 100}}


# --- TEST NEGATIF ---

def test_negatif_mapping_salah_harus_fail():
    """Descriptor _BotAttr("_salah") harus TIDAK sama dengan akses bot._price_cache."""
    obj = _make()
    obj.bot._price_cache = {"benar": 1}
    wrong = _BotAttr("_price_cache_salah")
    # akses lewat descriptor salah: karena lazy=False, attribute bot._price_cache_salah
    # tidak ada -> AttributeError. Itu bukti mapping beda.
    with pytest.raises(AttributeError):
        wrong.__get__(obj)
