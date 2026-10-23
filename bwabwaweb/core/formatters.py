# core/formatters.py — formatter angka murni Python (netral, tanpa Discord).
# Diekstrak dari services/spy/utils.py::fmt_k (session 29 Sep, zero logic change).

from __future__ import annotations


def fmt_compact(v: float) -> str:
    """Format angka ringkas: B (miliar) / M (juta) / K (ribu).
    Contoh: 1_500 -> '1.5K', 2_500_000 -> '2.50M', 3_000_000_000 -> '3.00B'.
    """
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:.0f}"
