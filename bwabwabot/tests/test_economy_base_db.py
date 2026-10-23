# tests/test_economy_base_db.py — behavior test base_db (manual_donations)
"""Differential: mock db_pool.table, rekam chain, assert persis.
Bukan byte-conservation — Fase 1 ubah signature (self dilepas).
Test negatif: kalau chain berubah, test FAIL.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from services.economy import base_db


class _ChainRecorder:
    """Mock chainable: rekam tiap .method(args) yang dipanggil."""

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
    monkeypatch.setattr(base_db.db_pool, "table", _table)


# --- get_manual_donations ---

def test_get_manual_donations_chain(monkeypatch):
    chain = _ChainRecorder(result=[{"id": 1}])
    _patch_table(monkeypatch, chain)
    out = asyncio.run(base_db.get_manual_donations("ID", "2026-01-01"))
    assert out == [{"id": 1}]
    names = [c[0] for c in chain.calls]
    assert names == ["table", "select", "eq", "gte", "order", "execute"]
    assert chain.calls[0][1] == ("manual_donations",)
    assert chain.calls[2][1] == ("country_id", "ID")
    assert chain.calls[3][1] == ("donation_date", "2026-01-01")


def test_get_manual_donations_empty_result(monkeypatch):
    chain = _ChainRecorder(result=None)
    _patch_table(monkeypatch, chain)
    out = asyncio.run(base_db.get_manual_donations("ID", "2026-01-01"))
    assert out == []


def test_get_manual_donations_exception(monkeypatch):
    def _table(_):
        raise RuntimeError("boom")
    monkeypatch.setattr(base_db.db_pool, "table", _table)
    out = asyncio.run(base_db.get_manual_donations("ID", "2026-01-01"))
    assert out == []


# --- add_manual_donation ---

def test_add_manual_donation_chain(monkeypatch):
    chain = _ChainRecorder(result=[{"id": 99}])
    _patch_table(monkeypatch, chain)
    out = asyncio.run(base_db.add_manual_donation("ID", "bob", 10.5, "2026-01-01", "admin"))
    assert out == {"id": 99}
    names = [c[0] for c in chain.calls]
    assert names == ["table", "insert", "execute"]
    payload = chain.calls[1][1][0]
    assert payload == {
        "country_id": "ID", "username": "bob", "amount": 10.5,
        "donation_date": "2026-01-01", "added_by": "admin",
    }


def test_add_manual_donation_empty(monkeypatch):
    chain = _ChainRecorder(result=[])
    _patch_table(monkeypatch, chain)
    out = asyncio.run(base_db.add_manual_donation("ID", "bob", 1.0, "2026-01-01", "a"))
    assert out is None


def test_add_manual_donation_exception(monkeypatch):
    def _table(_):
        raise RuntimeError("boom")
    monkeypatch.setattr(base_db.db_pool, "table", _table)
    out = asyncio.run(base_db.add_manual_donation("ID", "bob", 1.0, "2026-01-01", "a"))
    assert out is None


# --- delete_manual_donation ---

def test_delete_manual_donation_chain(monkeypatch):
    chain = _ChainRecorder(result=[{"id": 5}])
    _patch_table(monkeypatch, chain)
    out = asyncio.run(base_db.delete_manual_donation(5))
    assert out is True
    names = [c[0] for c in chain.calls]
    assert names == ["table", "delete", "eq", "execute"]
    assert chain.calls[2][1] == ("id", 5)


def test_delete_manual_donation_false(monkeypatch):
    chain = _ChainRecorder(result=[])
    _patch_table(monkeypatch, chain)
    out = asyncio.run(base_db.delete_manual_donation(5))
    assert out is False


# --- TEST NEGATIF: verifier harus bisa FAIL ---

def test_negatif_chain_rusak_harus_fail(monkeypatch):
    """Kalau .eq dipanggil sebelum .select, chain harus beda dari ekspektasi."""
    chain = _ChainRecorder(result=[{"id": 1}])

    # sengaja urutan salah: eq duluan
    def _table(_):
        chain.calls.append(("table", ("manual_donations",), {}))
        chain.eq("country_id", "ID")
        chain.select("id")
        chain.execute()
        return chain

    monkeypatch.setattr(base_db.db_pool, "table", _table)
    asyncio.run(base_db.get_manual_donations("ID", "2026-01-01"))
    names = [c[0] for c in chain.calls]
    expected = ["table", "select", "eq", "gte", "order", "execute"]
    assert names != expected, "TEST NEGATIF GAGAL: chain rusak harus beda dari expected"
