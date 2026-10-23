# services/economy/db_history.py — baca price_history dari app_db (diekstrak 28 Sep 2026)

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from services.db import pool as db_pool

log = logging.getLogger("WarEraBot.db_history")


# --- price history ---

async def get_price_history(item_name: str, hours: int = 720) -> list[dict]:
    """Riwayat harga 1 item dari app_db."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = await asyncio.to_thread(
            lambda: (
                db_pool.table("price_history")
                .select("price, recorded_at, volume")
                .eq("item_name", item_name)
                .gte("recorded_at", cutoff)
                .order("recorded_at", desc=False)
                .execute()
            )
        )
        return result or []
    except Exception as exc:
        log.error(f"get_price_history({item_name}): {exc}")
        return []
