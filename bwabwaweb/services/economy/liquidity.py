# services/economy/liquidity.py — skor liquidity (math murni, tanpa state cog)
"""
Logic skor liquidity untuk item:
- Input: history_days, median_notional_30d, anchor (dict dari DB)
- Output: LiquidityScoreResult (TypedDict)

Dipisah dari cogs/economy/base.py supaya bisa dipakai web API
tanpa lewat get_cog(). Murni: no state, no Discord, no DB call.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional, TypedDict

log = logging.getLogger("WarEraBot.economy.liquidity")

# --- calibration ---
# NOTE: histori price_history baru mulai 2026-07-04, jadi 60 dulu (bukan 90) —
# naikkan begitu histori genap.
SCORE_MIN_HISTORY_DAYS = 7     # < ini  -> skor None, item exclude dari analisis
SCORE_ESTABLISHED_DAYS = 30    # >= ini -> "established", else "provisional"

# Formula linear — reproduksi 3 titik bentuk lama yang nonlinear.
MARGIN_HIGH, MARGIN_LOW = 5.0, 15.0
WEIGHT_TECH_LOW, WEIGHT_TECH_HIGH = 0.20, 0.60


class LiquidityScoreResult(TypedDict):
    score: Optional[float]           # None = insufficient data, item di-hide
    raw_score: Optional[float]       # sebelum clamp
    margin_pct: Optional[float]
    weight_tech: Optional[float]
    weight_intr: Optional[float]
    liquidity_basis: Optional[str]   # "established" | "provisional" | None
    liquidity_history_days: int


def _score_to_params(score: float) -> tuple[float, float, float]:
    """margin_pct, weight_tech, weight_intr dari score [0,1] — formula linear."""
    margin_pct = MARGIN_LOW - (MARGIN_LOW - MARGIN_HIGH) * score
    weight_tech = WEIGHT_TECH_LOW + (WEIGHT_TECH_HIGH - WEIGHT_TECH_LOW) * score
    weight_intr = 1.0 - weight_tech
    return margin_pct, weight_tech, weight_intr


def _anchor_age_days(anchor: Optional[dict]) -> Optional[int]:
    """Umur anchor (hari) sejak calibrated_at. None = tidak diketahui."""
    if not anchor:
        return None
    calibrated = anchor.get("calibrated_at")
    if not calibrated:
        return None
    try:
        if isinstance(calibrated, str):
            calibrated = datetime.fromisoformat(calibrated.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - calibrated).days
    except (ValueError, TypeError):
        return None


def _compute_liquidity_score(
    item: str,
    history_days: int,
    median_notional_30d: Optional[float],
    anchor: Optional[dict],
) -> LiquidityScoreResult:
    """Data item + anchor -> skor liquidity + parameter turunan.

    Kegagalan data = skor None (item disembunyikan dari analisis), bukan
    error dan bukan nilai darurat.
    """
    empty: LiquidityScoreResult = {
        "score": None, "raw_score": None, "margin_pct": None,
        "weight_tech": None, "weight_intr": None,
        "liquidity_basis": None, "liquidity_history_days": history_days,
    }

    if history_days < SCORE_MIN_HISTORY_DAYS:
        return empty

    if median_notional_30d is None or median_notional_30d <= 0:
        return empty

    # anchor belum pernah dikalibrasi -> insufficient data, bukan error
    if anchor is None:
        log.warning(
            f"_compute_liquidity_score({item}): tidak ada baris liquidity_anchors "
            "— treated sebagai insufficient data. Kalau ini muncul terus, "
            "jalankan recalibrate_liquidity_anchors(force=True) / SQL bootstrap §F."
        )
        return empty

    min_a = anchor.get("min_anchor_log10")
    max_a = anchor.get("max_anchor_log10")
    if min_a is None or max_a is None or max_a <= min_a:
        log.error(f"_compute_liquidity_score({item}): anchor korup (max<=min), skip.")
        return empty

    raw = (math.log10(median_notional_30d) - min_a) / (max_a - min_a)
    score = max(0.0, min(1.0, raw))  # clamp — raw disimpan terpisah

    margin_pct, weight_tech, weight_intr = _score_to_params(score)
    basis = "established" if history_days >= SCORE_ESTABLISHED_DAYS else "provisional"

    return {
        "score": score,
        "raw_score": raw,
        "margin_pct": margin_pct,
        "weight_tech": weight_tech,
        "weight_intr": weight_intr,
        "liquidity_basis": basis,
        "liquidity_history_days": history_days,
    }
