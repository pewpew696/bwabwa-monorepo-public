# services/web_api_state.py — state holder web_api, decouple dari _bot.*
"""Ganti akses langsung `_bot.X` di web_api/ dengan accessor tipis.

Pola: set_bot() dipanggil sekali saat startup (dari web_api.init_web_api).
Setelah itu route cukup panggil get_session(), dll —
tidak sentuh `_bot` langsung.

Alasan: kalau nanti split proses Flask/Discord, cukup ubah isi accessor
(mis. get_session() buka koneksi sendiri di proses web), bukan 35
call-site di 7 file.

IMPROVEMENT (bukan zero-change refactor):
Accessor di sini menambah guard `_bot_ref is None` + log.warning —
kode lama langsung AttributeError (bocor 500 + stack trace ke browser).
Dengan guard, user dapat response netral; detail tetap di log server.
Log TIDAK pernah sampai ke browser (stream terpisah: journald vs HTTP).
"""
from __future__ import annotations

import logging

log = logging.getLogger("WarEraBot.web_api_state")

# --- state ---

_bot_ref = None


def set_bot(bot) -> None:
    """Dipanggil sekali dari web_api.init_web_api() saat startup."""
    global _bot_ref
    _bot_ref = bot


# --- accessor ---

def get_bot():
    """Akses bot mentah — hindari kalau bisa, pakai accessor spesifik."""
    if _bot_ref is None:
        log.warning("get_bot() dipanggil sebelum set_bot() — return None")
        return None
    return _bot_ref


def get_session():
    if _bot_ref is None:
        log.warning("get_session() dipanggil sebelum set_bot() — return None")
        return None
    return _bot_ref._session


def get_price_cache() -> dict:
    if _bot_ref is None:
        log.warning("get_price_cache() dipanggil sebelum set_bot() — return {}")
        return {}
    return _bot_ref._price_cache


def get_price_history() -> dict:
    if _bot_ref is None:
        log.warning("get_price_history() dipanggil sebelum set_bot() — return {}")
        return {}
    return _bot_ref._price_history


def get_volume_cache() -> dict:
    if _bot_ref is None:
        log.warning("get_volume_cache() dipanggil sebelum set_bot() — return {}")
        return {}
    return getattr(_bot_ref, "_volume_cache", {}) or {}


def get_manual_overrides() -> dict:
    if _bot_ref is None:
        log.warning("get_manual_overrides() sebelum set_bot() - return {}")
        return {}
    return getattr(_bot_ref, "_manual_overrides", {})


def get_bonus_breakdown() -> dict:
    if _bot_ref is None:
        log.warning("get_bonus_breakdown() sebelum set_bot() - return {}")
        return {}
    return getattr(_bot_ref, "_bonus_breakdown_cache", {})


def get_country_tax_cache() -> dict:
    if _bot_ref is None:
        log.warning("get_country_tax_cache() sebelum set_bot() - return {}")
        return {}
    return getattr(_bot_ref, "_country_tax_cache", {})


def get_cog(name: str):
    if _bot_ref is None:
        log.warning(f"get_cog({name!r}) dipanggil sebelum set_bot() — return None")
        return None
    return _bot_ref.get_cog(name)
