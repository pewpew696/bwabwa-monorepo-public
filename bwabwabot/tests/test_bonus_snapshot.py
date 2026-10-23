# tests/test_bonus_snapshot.py — differential test db_save_bonus_snapshot
"""Mock local_session, rekam SQL + args. Test negatif: breakdown kosong -> no-op."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from services.db import helpers


class _MockCursor:
    def __init__(self):
        self.executes: list[tuple] = []
        self.executemany_calls: list[tuple] = []

    def execute(self, sql, params=None):
        self.executes.append((sql.strip(), params))

    def executemany(self, sql, rows):
        self.executemany_calls.append((sql.strip(), rows))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _MockConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass


def _patch_session(monkeypatch, cur):
    @contextmanager
    def _fake_session(commit=False):
        yield cur

    monkeypatch.setattr(helpers, "local_session", _fake_session)


# --- test utama ---

def test_bonus_snapshot_basic(monkeypatch):
    cur = _MockCursor()
    _patch_session(monkeypatch, cur)
    ends = datetime(2026, 10, 2, 5, 0, tzinfo=timezone.utc)
    breakdown = {
        "Iron": [("Kyrgyzstan", 60.0), ("Botswana", 55.0)],
        "Steel": [("Egypt", 46.0)],
    }
    deposit_ends = {"Iron": {"Botswana": ends}}
    tax_cache = {"Kyrgyzstan": 10.0, "Botswana": 10.0, "Egypt": 10.0}

    out = asyncio.run(helpers.db_save_bonus_snapshot(breakdown, deposit_ends, tax_cache))
    assert out == 3

    # DELETE (1x)
    assert len(cur.executes) == 1
    sql_del, params_del = cur.executes[0]
    assert "DELETE FROM item_bonus_deposits" in sql_del
    assert set(params_del[0]) == {"Iron", "Steel"}

    # INSERT bonus (1x executemany)
    assert len(cur.executemany_calls) == 2
    sql_b, rows_b = cur.executemany_calls[0]
    assert "INSERT INTO item_bonus_deposits" in sql_b
    assert len(rows_b) == 3
    # cek urutan rank
    iron_rows = [r for r in rows_b if r[0] == "Iron"]
    assert iron_rows[0][3] == 1 and iron_rows[0][1] == "Kyrgyzstan"
    assert iron_rows[1][3] == 2 and iron_rows[1][1] == "Botswana"
    # cek ends_at hanya di Botswana
    assert iron_rows[0][4] is None
    assert iron_rows[1][4] == ends

    # INSERT tax (1x executemany)
    sql_t, rows_t = cur.executemany_calls[1]
    assert "country_tax_snapshot" in sql_t
    assert "ON CONFLICT" in sql_t
    assert len(rows_t) == 3


def test_bonus_snapshot_no_tax(monkeypatch):
    cur = _MockCursor()
    _patch_session(monkeypatch, cur)
    breakdown = {"Iron": [("Kyrgyzstan", 60.0)]}
    asyncio.run(helpers.db_save_bonus_snapshot(breakdown, {}, {}))
    # DELETE + INSERT bonus, tidak ada tax
    assert len(cur.executes) == 1
    assert len(cur.executemany_calls) == 1


def test_bonus_snapshot_tax_none_skipped(monkeypatch):
    """tax_pct None harus dilewati, bukan crash."""
    cur = _MockCursor()
    _patch_session(monkeypatch, cur)
    breakdown = {"Iron": [("Kyrgyzstan", 60.0)]}
    tax_cache = {"Kyrgyzstan": None, "Botswana": 5.0}
    asyncio.run(helpers.db_save_bonus_snapshot(breakdown, {}, tax_cache))
    _, rows_t = cur.executemany_calls[1]
    assert len(rows_t) == 1
    assert rows_t[0][0] == "Botswana"


# --- TEST NEGATIF ---

def test_negatif_breakdown_kosong_no_db(monkeypatch):
    """Kalau breakdown kosong, tidak boleh ada panggilan DB sama sekali."""
    cur = _MockCursor()
    _patch_session(monkeypatch, cur)
    out = asyncio.run(helpers.db_save_bonus_snapshot({}, {}, {"X": 1.0}))
    assert out == 0
    assert cur.executes == []
    assert cur.executemany_calls == []


def test_negatif_delete_dibatasi_item(monkeypatch):
    """DELETE harus punya WHERE item_name = ANY(...), bukan tanpa WHERE."""
    cur = _MockCursor()
    _patch_session(monkeypatch, cur)
    asyncio.run(helpers.db_save_bonus_snapshot(
        {"Iron": [("K", 1.0)]}, {}, {}
    ))
    sql_del = cur.executes[0][0]
    assert "WHERE" in sql_del, "TEST NEGATIF: DELETE harus WHERE"
    assert "item_name = ANY" in sql_del
