# market/auth.py — token WarEra + auth header helpers
from __future__ import annotations

import logging
import os

log = logging.getLogger("WarEraBot.market")


_WARERA_API_TOKEN: str = os.environ.get("WARERA_API_KEY", "")

_WARERA_DONATION_API_TOKEN: str = os.environ.get("WARERA_API_KEY_DONATION", "") or _WARERA_API_TOKEN

_WARERA_PAGINATE_TOKEN: str = os.environ.get("WARERA_API_KEY_PAGINATE", "") or _WARERA_API_TOKEN
_WARERA_DETAIL1_TOKEN:  str = os.environ.get("WARERA_API_KEY_DETAIL1", "") or _WARERA_API_TOKEN
_WARERA_DETAIL2_TOKEN:  str = os.environ.get("WARERA_API_KEY_DETAIL2", "") or _WARERA_API_TOKEN

_WARERA_HUB_TOKEN: str = os.environ.get("WARERA_API_KEY_HUB", "") or _WARERA_API_TOKEN


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Origin":  "https://app.warera.io",
    "Referer": "https://app.warera.io/",
}


def _auth_headers() -> dict:
    h = dict(HEADERS)
    if _WARERA_API_TOKEN:
        h["X-Api-Key"] = _WARERA_API_TOKEN
    return h


def _donation_auth_headers() -> dict:
    h = dict(HEADERS)
    if _WARERA_DONATION_API_TOKEN:
        h["X-Api-Key"] = _WARERA_DONATION_API_TOKEN
    return h


def donation_headers() -> dict:
    """Wrapper publik buat economy.py — semua request fitur donasi pake
    token donasi, gak numpang quota token umum."""
    return _donation_auth_headers()


def _paginate_auth_headers() -> dict:
    h = dict(HEADERS)
    if _WARERA_PAGINATE_TOKEN:
        h["X-Api-Key"] = _WARERA_PAGINATE_TOKEN
    return h


def _detail1_auth_headers() -> dict:
    h = dict(HEADERS)
    if _WARERA_DETAIL1_TOKEN:
        h["X-Api-Key"] = _WARERA_DETAIL1_TOKEN
    return h


def _detail2_auth_headers() -> dict:
    h = dict(HEADERS)
    if _WARERA_DETAIL2_TOKEN:
        h["X-Api-Key"] = _WARERA_DETAIL2_TOKEN
    return h


def _hub_auth_headers() -> dict:
    h = dict(HEADERS)
    if _WARERA_HUB_TOKEN:
        h["X-Api-Key"] = _WARERA_HUB_TOKEN
    return h


def log_token_status() -> None:
    """Panggil sekali pas startup — kasih tau token mana yang beneran
    dedicated vs diam-diam fallback ke token utama (env var belum diisi)."""
    checks = [
        ("WARERA_API_KEY_DONATION", _WARERA_DONATION_API_TOKEN),
        ("WARERA_API_KEY_PAGINATE", _WARERA_PAGINATE_TOKEN),
        ("WARERA_API_KEY_DETAIL1",  _WARERA_DETAIL1_TOKEN),
        ("WARERA_API_KEY_DETAIL2",  _WARERA_DETAIL2_TOKEN),
        ("WARERA_API_KEY_HUB",      _WARERA_HUB_TOKEN),
    ]
    for env_name, resolved_token in checks:
        raw_env_value = os.environ.get(env_name, "")
        if raw_env_value and resolved_token == raw_env_value:
            log.info(f"[STARTUP] {env_name}: dedicated (OK)")
        else:
            log.warning(
                f"[STARTUP] {env_name}: FALLBACK ke token utama — env var belum "
                f"di-set, kuota rate-limit numpang WARERA_API_KEY biasa."
            )
