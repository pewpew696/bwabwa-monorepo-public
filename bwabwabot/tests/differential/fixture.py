# tests/differential/fixture.py — fake bot + mock deterministik untuk _fp_analyze
"""
Bangun FairPriceCommands dengan state palsu tapi deterministik.
Tujuan: bisa jalankan `_fp_analyze(item, orderbook)` tanpa Discord/DB.

Semua nilai di-fix — tidak boleh ada waktu "sekarang" yang bikin non-deterministik.
Untuk `_fp_trend_30d` (async, panggil DB) di-mock langsung.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone, timedelta

from cogs.economy.fairprice import FairPriceCommands
from services.economy.constants import PRODUCTION_CHAIN


# Timestamp FIXED — biar snapshot reproducible (bukan datetime.now()).
FIXED_NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
FIXED_PRICE_TS = FIXED_NOW - timedelta(hours=1)


class _FakeBot:
    """Bot minimal — cuma nampung state cache yang dibaca cog."""
    pass


def _make_price_cache() -> dict[str, float]:
    """Harga buat: tier-1 (pp_value) + input produksi + item sampel."""
    return {
        # Tier-1 (buat pp_value)
        "Iron": 100.0,
        "Wood": 80.0,
        "Grain": 60.0,
        "Limestone": 120.0,
        # Input produksi
        "Petroleum": 90.0,
        "Lead": 50.0,
        "Livestock": 200.0,
        "Fish": 300.0,
        "Mysterious Plant": 500.0,
        # Item sampel
        "Steel": 1000.0,
        "Pill": 1200.0,
        "Scraps": 40.0,
        "Case 1": 5000.0,
        "Case 2": 8000.0,
        # Output yang dipakai sebagai input lain
        "Bread": 700.0,
        "Cooked Fish": 900.0,
        "Steak": 1500.0,
        "Oil": 500.0,
        "Concrete": 1500.0,
        "Paper": 400.0,
        "Ammo": 350.0,
        "Light Ammo": 100.0,
        "Heavy Ammo": 1200.0,
    }


def _make_liquidity_cache() -> dict:
    """LiquidityScoreResult untuk tiap producible sampel."""
    base = {
        "score": 0.7,
        "raw_score": 0.7,
        "margin_pct": 2.0,
        "weight_tech": 0.6,
        "weight_intr": 0.4,
        "liquidity_basis": "established",
        "liquidity_history_days": 60,
    }
    return {
        "Iron": dict(base),
        "Steel": dict(base, score=0.5, raw_score=0.5, margin_pct=2.5, weight_tech=0.5, weight_intr=0.5),
        "Pill": dict(base, score=0.9, raw_score=0.9, margin_pct=1.0, weight_tech=0.8, weight_intr=0.2),
    }


def _make_price_history() -> dict:
    """Deque histori (ts, price) per item. Beberapa titik biar technical_value kehitung."""
    def _pts(prices):
        # Pakai runtime now biar selalu masuk window 7 hari (bukan FIXED_NOW).
        base = datetime.now(timezone.utc) - timedelta(days=3)
        return deque((base + timedelta(hours=i), p) for i, p in enumerate(prices))

    return {
        "Iron": _pts([95.0, 98.0, 100.0, 102.0]),
        "Steel": _pts([980.0, 990.0, 1000.0]),
        "Pill": _pts([1150.0, 1180.0, 1200.0]),
        "Scraps": _pts([38.0, 39.0, 40.0]),
        "Case 1": _pts([4900.0, 5000.0, 5100.0]),
        # Case 2 sengaja kosong -> test branch "no history"
    }


def _make_price_extremes() -> dict:
    return {
        "Iron": {
            "recorded_high": 150.0, "recorded_high_date": "2026-08-15",
            "recorded_low": 80.0, "recorded_low_date": "2026-07-20",
            "tracked_since": "2026-07-01",
        },
        "Steel": {
            "recorded_high": 1500.0, "recorded_high_date": "2026-08-10",
            "recorded_low": 800.0, "recorded_low_date": "2026-07-05",
            "tracked_since": "2026-07-01",
        },
    }


def make_cog(
    *,
    median_bonus: tuple[float, str] = (10.0, "median"),
    best_bonus: tuple[float, str] = (15.0, "auto"),
    trend: tuple[str, str] = ("⚪ Sideways (0.0%)", "Sideways"),
    anchor_age_days: int = 10,
    liq_score_override: float | None = None,
    spread_override: tuple[float, float] | None = None,
) -> FairPriceCommands:
    """FairPriceCommands dengan mock deterministik.

    Semua parameter default = fixed. Ubah kalau mau test skenario beda.
    """
    bot = _FakeBot()
    bot._price_cache = _make_price_cache()
    liq_cache = _make_liquidity_cache()
    if liq_score_override is not None:
        for k in liq_cache:
            liq_cache[k]["score"] = liq_score_override
            liq_cache[k]["raw_score"] = liq_score_override
    bot._liquidity_score_cache = liq_cache
    bot._liquidity_anchor_meta = {
        "calibrated_at": "2026-09-17T00:00:00+00:00",
        "anchor_age_days": anchor_age_days,
    }
    bot._price_extremes_cache = _make_price_extremes()
    bot._price_history = _make_price_history()
    # Placeholder — gak dipakai di _fp_analyze (sudah pindah ke services)
    bot._auto_bonus_cache = {}
    bot._median_bonus_cache = {}
    bot._manual_overrides = {}

    cog = FairPriceCommands.__new__(FairPriceCommands)
    cog.bot = bot

    # Mock method yang butuh DB / non-deterministik
    cog._get_median_bonus = lambda item: median_bonus
    cog._get_bonus = lambda item: best_bonus

    async def _fp_trend_30d(item: str) -> tuple[str, str]:
        return trend
    cog._fp_trend_30d = _fp_trend_30d

    return cog


# --- Sampel input (item + orderbook) ---

SAMPLE_CASES = [
    {
        "id": "iron_producible",
        "item": "Iron",
        "orderbook": {"best_bid": 95.0, "best_ask": 105.0, "buy_vol": 1000, "sell_vol": 1500},
    },
    {
        "id": "steel_producible",
        "item": "Steel",
        "orderbook": {"best_bid": 990.0, "best_ask": 1020.0, "buy_vol": 200, "sell_vol": 300},
    },
    {
        "id": "pill_producible",
        "item": "Pill",
        "orderbook": {"best_bid": 1180.0, "best_ask": 1220.0, "buy_vol": 50, "sell_vol": 80},
    },
    {
        "id": "scraps_nonproducible",
        "item": "Scraps",
        "orderbook": {"best_bid": 38.0, "best_ask": 42.0, "buy_vol": 5000, "sell_vol": 6000},
    },
    {
        "id": "case1_nonproducible",
        "item": "Case 1",
        "orderbook": {"best_bid": 4900.0, "best_ask": 5100.0, "buy_vol": 10, "sell_vol": 12},
    },
    {
        "id": "iron_orderbook_failed",
        "item": "Iron",
        "orderbook": "error",  # sentinel — fetch gagal
    },
    {
        "id": "case2_no_history_nonproducible",
        "item": "Case 2",
        "orderbook": None,  # tidak ada orderbook
    },
    # --- sampel yang hit risk High (risk_points >= 4) ---
    {
        "id": "iron_wide_lowliq_highconf_missing",
        "item": "Iron",
        # Wide spread (40%) + liq_score rendah (0.1 < 0.35)
        "orderbook": {"best_bid": 80.0, "best_ask": 120.0, "buy_vol": 100, "sell_vol": 200},
        "_cog_kwargs": {"liq_score_override": 0.1},
    },
    {
        "id": "steel_wide_lowliq_highconf_missing",
        "item": "Steel",
        "orderbook": {"best_bid": 800.0, "best_ask": 1200.0, "buy_vol": 50, "sell_vol": 80},
        "_cog_kwargs": {"liq_score_override": 0.05},
    },
]
