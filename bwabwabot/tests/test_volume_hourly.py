# tests/test_volume_hourly.py — differential test db_save_volume_hourly + _parse_created_at
"""Mock db_pool.table().upsert().execute(), assert rows persis.
Test negatif: rows kosong -> return 0 tanpa call DB."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from services.db import helpers
from market.prices import _parse_created_at


class _MockTable:
    def __init__(self, affected=0):
        self._affected = affected
        self.upsert_args: list[tuple] = []
        self.upsert_kwargs: list[dict] = []

    def upsert(self, rows, on_conflict=None, **kwargs):
        self.upsert_args.append((rows,))
        self.upsert_kwargs.append({"on_conflict": on_conflict, **kwargs})
        return self

    def execute(self):
        return self._affected


def _patch_table(monkeypatch, mock):
    monkeypatch.setattr(helpers.db_pool, "table", lambda name: mock)


# --- db_save_volume_hourly ---

def test_save_volume_hourly_basic(monkeypatch):
    mock = _MockTable(affected=3)
    _patch_table(monkeypatch, mock)
    h1 = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)
    h2 = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)
    volume = {
        "Iron":  {"tx": 2, "qty": 100, "qty_h": 4.2, "by_hour": {h1: 60, h2: 40}},
        "Steel": {"tx": 1, "qty": 50,  "qty_h": 2.1, "by_hour": {h1: 50}},
    }
    out = asyncio.run(helpers.db_save_volume_hourly(volume))
    assert out == 3
    rows = mock.upsert_args[0][0]
    assert len(rows) == 3
    assert mock.upsert_kwargs[0]["on_conflict"] == "item_name, hour_start"
    pairs = sorted((r["item_name"], r["qty"]) for r in rows)
    assert pairs == [("Iron", 40), ("Iron", 60), ("Steel", 50)]


def test_save_volume_hourly_empty(monkeypatch):
    mock = _MockTable(affected=0)
    _patch_table(monkeypatch, mock)
    out = asyncio.run(helpers.db_save_volume_hourly({}))
    assert out == 0
    assert mock.upsert_args == []


def test_save_volume_hourly_no_by_hour(monkeypatch):
    """Item tanpa by_hour (mis. refresh lama) -> tidak error, tidak ada row."""
    mock = _MockTable(affected=0)
    _patch_table(monkeypatch, mock)
    out = asyncio.run(helpers.db_save_volume_hourly({"Iron": {"tx": 0, "qty": 0}}))
    assert out == 0
    assert mock.upsert_args == []


def test_save_volume_hourly_exception(monkeypatch):
    def _raise(_):
        raise RuntimeError("boom")
    monkeypatch.setattr(helpers.db_pool, "table", _raise)
    h1 = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)
    out = asyncio.run(helpers.db_save_volume_hourly({"Iron": {"by_hour": {h1: 10}}}))
    assert out == 0


# --- _parse_created_at ---

def test_parse_created_at_z_suffix():
    dt = _parse_created_at("2026-09-30T01:23:45Z")
    assert dt == datetime(2026, 9, 30, 1, 23, 45, tzinfo=timezone.utc)


def test_parse_created_at_offset():
    dt = _parse_created_at("2026-09-30T01:23:45+00:00")
    assert dt == datetime(2026, 9, 30, 1, 23, 45, tzinfo=timezone.utc)


def test_parse_created_at_none():
    assert _parse_created_at(None) is None
    assert _parse_created_at("") is None


def test_parse_created_at_invalid():
    assert _parse_created_at("bukan-tanggal") is None


# --- TEST NEGATIF ---

def test_negatif_rows_kosong_tidak_upsert(monkeypatch):
    """Kalau by_hour kosong, jangan panggil upsert sama sekali."""
    mock = _MockTable(affected=0)
    _patch_table(monkeypatch, mock)
    asyncio.run(helpers.db_save_volume_hourly({"Iron": {"by_hour": {}}}))
    assert mock.upsert_args == [], "TEST NEGATIF: upsert harus tidak terpanggil"
