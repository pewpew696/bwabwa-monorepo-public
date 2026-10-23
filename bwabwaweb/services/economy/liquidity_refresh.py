# services/economy/liquidity_refresh.py — fetch anchor + item notional (diekstrak 29 Sep 2026)

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from services.db import pool as db_pool
from services.economy.constants import PRODUCTION_CHAIN

log = logging.getLogger("WarEraBot.economy_liquidity_refresh")

LOOKBACK_DAYS = 60
MIN_BASKET_HISTORY_DAYS = 60


async def fetch_latest_anchor() -> Optional[dict]:
    """Baris anchor terbaru; None kalau tabel kosong (bukan error)."""
    try:
        result = await asyncio.to_thread(
            lambda: (
                db_pool.table("liquidity_anchors")
                .select("*")
                .order("calibrated_at", desc=True)
                .limit(1)
                .execute()
            )
        )
        rows = result or []
        return rows[0] if rows else None
    except Exception as exc:
        log.error(f"fetch_latest_anchor(): {exc}")
        return None


async def get_item_notional_history(item: str) -> tuple[int, Optional[float]]:
    """Return (history_days, median_notional_30d | None)."""
    try:
        cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        def _query_median():
            # PERCENTILE_CONT gak bisa lewat query-builder, wajib RPC
            return db_pool.rpc(
                "item_median_notional_30d", {"p_item_name": item, "p_cutoff": cutoff_30d}
            ).execute()

        def _query_span():
            return (
                db_pool.table("price_history")
                .select("recorded_at")
                .eq("item_name", item)
                .order("recorded_at", desc=False)
                .limit(1)
                .execute()
            )

        median_result, span_result = await asyncio.gather(
            asyncio.to_thread(_query_median),
            asyncio.to_thread(_query_span),
        )
        median_rows = median_result or []
        span_rows = span_result or []

        median_notional = median_rows[0]["median_notional"] if median_rows else None

        if not span_rows:
            return 0, median_notional
        earliest = datetime.fromisoformat(span_rows[0]["recorded_at"])
        history_days = (datetime.now(timezone.utc) - earliest).days
        return history_days, median_notional
    except Exception as exc:
        log.error(f"get_item_notional_history({item}): {exc}")
        return 0, None


async def recalibrate_anchors(force: bool = False) -> Optional[dict]:
    """Cron bulanan / manual (force=True). Wajib dijalankan sekali saat
    deploy (bootstrap).

    Basket = item PRODUCTION_CHAIN dengan >= MIN_BASKET_HISTORY_DAYS hari
    histori. Insert baris BARU, bukan update — kalau job gagal, anchor
    lama tetap valid (pembaca selalu ambil yang terbaru).
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=MIN_BASKET_HISTORY_DAYS)).isoformat()

        def _query():
            return db_pool.rpc(
                "liquidity_basket_medians",
                {"cutoff": cutoff, "lookback_days": LOOKBACK_DAYS},
            ).execute()

        result = await asyncio.to_thread(_query)
        rows = result or []
        # rows: [{"item_name", "median_notional", "history_days"}, ...]
        # filter Python redundant dengan cutoff SQL (defense in depth)
        eligible = [
            r for r in rows
            if r.get("item_name") in PRODUCTION_CHAIN
            and (r.get("history_days") or 0) >= MIN_BASKET_HISTORY_DAYS
            and (r.get("median_notional") or 0) > 0
        ]
        if len(eligible) < 2:
            log.error(
                f"recalibrate_anchors: basket eligible cuma {len(eligible)} item, "
                "butuh >= 2 buat min/max anchor. Kalibrasi DIBATALKAN, "
                "anchor lama (kalau ada) tetap dipakai."
            )
            return None

        min_row = min(eligible, key=lambda r: r["median_notional"])
        max_row = max(eligible, key=lambda r: r["median_notional"])

        new_anchor = {
            "min_anchor_log10": math.log10(min_row["median_notional"]),
            "max_anchor_log10": math.log10(max_row["median_notional"]),
            "min_item": min_row["item_name"],
            "max_item": max_row["item_name"],
            "basket_size": len(eligible),
            "lookback_days": LOOKBACK_DAYS,
        }

        def _insert():
            return db_pool.table("liquidity_anchors").insert(new_anchor).execute()

        await asyncio.to_thread(_insert)
        log.info(
            f"liquidity anchor recalibrated: min={new_anchor['min_item']} "
            f"max={new_anchor['max_item']} basket_size={len(eligible)} "
            f"lookback={LOOKBACK_DAYS}d force={force}"
        )
        return new_anchor
    except Exception as exc:
        log.error(f"recalibrate_anchors(force={force}): {exc}")
        return None
