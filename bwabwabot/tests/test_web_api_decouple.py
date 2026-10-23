# tests/test_web_api_decouple.py — verifier residual: web_api tidak akses _bot.*
"""File di web_api/ yang sudah pakai `web_api_state` TIDAK BOLEH akses
`_bot.*` / `_web_api._bot.*` / `web_api._bot.*` langsung.

Verifikasi struktural (bandingkan counter OLD vs NEW) dihapus 28 Sep:
sudah selesai masa refactor, tidak relevan lagi, dan akan selalu
komplain tiap ada fitur baru. Yang dijaga jangka panjang = residual
check (mencegah regresi akses _bot.*).

Negatif: 1 test memastikan verifier BISA FAIL kalau akses _bot baru muncul.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_API_DIR = ROOT / "web_api"


def _candidate_files() -> list[str]:
    return sorted(str(p.relative_to(ROOT)) for p in WEB_API_DIR.glob("*.py"))


def _find_direct_bot_accesses(src: str) -> list[tuple[int, str]]:
    """Semua akses `_bot.X`, `_web_api._bot.X`, `web_api._bot.X`."""
    leftover = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Attribute):
            v = n.value
            if isinstance(v, ast.Name) and v.id == "_bot":
                leftover.append((n.lineno, f"_bot.{n.attr}"))
            elif (isinstance(v, ast.Attribute) and v.attr == "_bot"
                  and isinstance(v.value, ast.Name)
                  and v.value.id in ("_web_api", "web_api")):
                leftover.append((n.lineno, f"{v.value.id}._bot.{n.attr}"))
    return leftover


def test_no_residual_bot_access_in_decoupled_files() -> None:
    """File yang sudah import web_api_state tidak boleh punya akses `_bot.` literal."""
    for rel in _candidate_files():
        src = (ROOT / rel).read_text()
        if "web_api_state" not in src:
            continue
        leftover = _find_direct_bot_accesses(src)
        assert not leftover, f"{rel}: sisa akses _bot.* -> {leftover}"


def test_negative_detects_extra_bot_access() -> None:
    """Verifier harus FAIL kalau ada akses _bot baru di file yang sudah decouple."""
    rel = "web_api/market_routes.py"
    src = (ROOT / rel).read_text()
    if "web_api_state" not in src:
        pytest.skip(f"{rel}: belum di-decouple")

    tampered = src.replace(
        "def get_prices():",
        "def get_prices():\n    _bot._session = None",
        1,
    )
    assert tampered != src, "tamper gagal (anchor tidak ketemu)"
    leftover = _find_direct_bot_accesses(tampered)
    assert leftover, "verifier buta: akses _bot baru tidak terdeteksi"


def test_negative_detects_bare_module_bot() -> None:
    """Bare `web_api._bot` / `_web_api._bot` harus terdeteksi (tanpa .X)."""
    assert _find_direct_bot_accesses("x = web_api._bot._session\n"), "web_api._bot lolos"
    assert _find_direct_bot_accesses("y = _web_api._bot._supabase\n"), "_web_api._bot lolos"
