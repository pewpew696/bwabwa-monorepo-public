# tests/test_liquidity_refresh.py — behavior test liquidity_refresh (fetch + notional)
"""Differential: mock db_pool, assert chain + return value.
Test negatif: chain berubah -> FAIL.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from services.economy import liquidity_refresh as lr


class _ChainRecorder:
    def __init__(self, result=None):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._result = result

    def __getattr__(self, name):
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return _rec

    def execute(self):
        self.calls.append(("execute", (), {}))
        return self._result


def _patch_table(monkeypatch, chain):
    def _table(name):
        chain.calls.append(("table", (name,), {}))
        return chain
    monkeypatch.setattr(lr.db_pool, "table", _table)


# --- fetch_latest_anchor ---

def test_fetch_latest_anchor_chain(monkeypatch):
    chain = _ChainRecorder(result=[{"id": 1, "calibrated_at": "2026-01-01"}])
    _patch_table(monkeypatch, chain)
    out = asyncio.run(lr.fetch_latest_anchor())
    assert out == {"id": 1, "calibrated_at": "2026-01-01"}
    names = [c[0] for c in chain.calls]
    assert names == ["table", "select", "order", "limit", "execute"]
    assert chain.calls[0][1] == ("liquidity_anchors",)


def test_fetch_latest_anchor_empty(monkeypatch):
    chain = _ChainRecorder(result=[])
    _patch_table(monkeypatch, chain)
    out = asyncio.run(lr.fetch_latest_anchor())
    assert out is None


def test_fetch_latest_anchor_exception(monkeypatch):
    def _table(_):
        raise RuntimeError("boom")
    monkeypatch.setattr(lr.db_pool, "table", _table)
    out = asyncio.run(lr.fetch_latest_anchor())
    assert out is None


# --- get_item_notional_history ---

def test_get_item_notional_history_full(monkeypatch):
    earliest = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()

    rpc_chain = _ChainRecorder(result=[{"median_notional": 500.0}])
    table_chain = _ChainRecorder(result=[{"recorded_at": earliest}])

    def _rpc(name, params):
        rpc_chain.calls.append(("rpc", (name, params), {}))
        return rpc_chain

    monkeypatch.setattr(lr.db_pool, "rpc", _rpc)
    _patch_table(monkeypatch, table_chain)

    days, median = asyncio.run(lr.get_item_notional_history("Iron"))
    assert days == 100
    assert median == 500.0
    assert rpc_chain.calls[0][1][0] == "item_median_notional_30d"
    assert rpc_chain.calls[0][1][1]["p_item_name"] == "Iron"
    tnames = [c[0] for c in table_chain.calls]
    assert tnames == ["table", "select", "eq", "order", "limit", "execute"]


def test_get_item_notional_history_no_span(monkeypatch):
    rpc_chain = _ChainRecorder(result=[{"median_notional": 100.0}])
    table_chain = _ChainRecorder(result=[])

    def _rpc(name, params):
        rpc_chain.calls.append(("rpc", (name, params), {}))
        return rpc_chain

    monkeypatch.setattr(lr.db_pool, "rpc", _rpc)
    _patch_table(monkeypatch, table_chain)

    days, median = asyncio.run(lr.get_item_notional_history("Iron"))
    assert days == 0
    assert median == 100.0


def test_get_item_notional_history_no_median(monkeypatch):
    earliest = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    rpc_chain = _ChainRecorder(result=[])
    table_chain = _ChainRecorder(result=[{"recorded_at": earliest}])

    def _rpc(name, params):
        rpc_chain.calls.append(("rpc", (name, params), {}))
        return rpc_chain

    monkeypatch.setattr(lr.db_pool, "rpc", _rpc)
    _patch_table(monkeypatch, table_chain)

    days, median = asyncio.run(lr.get_item_notional_history("Iron"))
    assert days == 5
    assert median is None


def test_get_item_notional_history_exception(monkeypatch):
    def _rpc(_, __):
        raise RuntimeError("boom")
    monkeypatch.setattr(lr.db_pool, "rpc", _rpc)
    out = asyncio.run(lr.get_item_notional_history("Iron"))
    assert out == (0, None)


# --- TEST NEGATIF ---

def test_negatif_chain_rusak_fetch(monkeypatch):
    """Kalau urutan chain beda, harus tidak sama dengan expected."""
    chain = _ChainRecorder(result=[{"id": 1}])

    def _table(_):
        chain.calls.append(("table", ("liquidity_anchors",), {}))
        chain.limit(1)
        chain.select("*")
        chain.execute()
        return chain

    monkeypatch.setattr(lr.db_pool, "table", _table)
    asyncio.run(lr.fetch_latest_anchor())
    names = [c[0] for c in chain.calls]
    expected = ["table", "select", "order", "limit", "execute"]
    assert names != expected, "TEST NEGATIF GAGAL"


# --- recalibrate_anchors ---

def test_recalibrate_anchors_ok(monkeypatch):
    rows = [
        {"item_name": "Iron", "median_notional": 100.0, "history_days": 90},
        {"item_name": "Steel", "median_notional": 1000.0, "history_days": 90},
        {"item_name": "Wood", "median_notional": 500.0, "history_days": 90},
    ]
    rpc_chain = _ChainRecorder(result=rows)
    insert_chain = _ChainRecorder(result=[{"id": 1}])

    def _rpc(name, params):
        rpc_chain.calls.append(("rpc", (name, params), {}))
        return rpc_chain

    def _table(_):
        insert_chain.calls.append(("table", ("liquidity_anchors",), {}))
        return insert_chain

    monkeypatch.setattr(lr.db_pool, "rpc", _rpc)
    monkeypatch.setattr(lr.db_pool, "table", _table)

    out = asyncio.run(lr.recalibrate_anchors(force=True))
    assert out is not None
    assert out["min_item"] == "Iron"
    assert out["max_item"] == "Steel"
    assert out["basket_size"] == 3
    assert out["lookback_days"] == lr.LOOKBACK_DAYS


def test_recalibrate_anchors_basket_too_small(monkeypatch):
    rows = [{"item_name": "Iron", "median_notional": 100.0, "history_days": 90}]
    rpc_chain = _ChainRecorder(result=rows)

    def _rpc(name, params):
        rpc_chain.calls.append(("rpc", (name, params), {}))
        return rpc_chain

    monkeypatch.setattr(lr.db_pool, "rpc", _rpc)
    out = asyncio.run(lr.recalibrate_anchors(force=False))
    assert out is None
