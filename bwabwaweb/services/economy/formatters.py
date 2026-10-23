# services/economy/formatters.py — formatter angka & waktu (murni, shared)
"""
Formatter kecil buat tampilan Discord & web:
- _fmt_*: angka -> string rapi (harga, persen, uang, compact)
- _format_*: datetime -> string sisa waktu / durasi

Murni: no state, no Discord, no DB call.
"""
from __future__ import annotations

from datetime import datetime, timezone

# _fmt_compact canonical di core/formatters.py::fmt_compact (session 29 Sep).
# Re-export alias supaya caller lama (cogs/economy/embeds.py) tetap jalan.
# Catatan: canonical punya tambahan B (miliar) — sebelumnya tanpa B.
from core.formatters import fmt_compact as _fmt_compact  # noqa: F401


def _fmt_price(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _fmt_pct(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _fmt_money(v: float) -> str:
    return f"{v:,.3f}".rstrip("0").rstrip(".")


def _format_remaining(expires_at: datetime) -> str:
    remaining = expires_at - datetime.now(timezone.utc)
    minutes   = max(0, int(remaining.total_seconds() // 60))
    return f"{minutes} min"


def _format_duration(expires_at: datetime) -> str:
    """Sisa waktu ke expires_at, format ringkas: '2d 5h', '13h 20m', '<1h'.
    Beda dari _format_remaining (menit doang, buat override manual)."""
    seconds = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return "<1h"
