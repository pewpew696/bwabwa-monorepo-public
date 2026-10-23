# services/economy/base_db.py — DB helper manual_donations (diekstrak 29 Sep 2026)

from __future__ import annotations

import asyncio
import logging

from services.db import pool as db_pool

log = logging.getLogger("WarEraBot.economy_base_db")


async def get_manual_donations(country_id: str, since_date: str) -> list[dict]:
    """since_date format 'YYYY-MM-DD' (UTC), inklusif."""
    try:
        result = await asyncio.to_thread(
            lambda: (
                db_pool.table("manual_donations")
                .select("id, username, amount, donation_date, added_by, created_at")
                .eq("country_id", country_id)
                .gte("donation_date", since_date)
                .order("donation_date", desc=True)
                .execute()
            )
        )
        return result or []
    except Exception as exc:
        log.error(f"get_manual_donations({country_id}): {exc}")
        return []


async def add_manual_donation(
    country_id: str, username: str, amount: float, donation_date: str, added_by: str
) -> dict | None:
    try:
        result = await asyncio.to_thread(
            lambda: (
                db_pool.table("manual_donations")
                .insert({
                    "country_id":     country_id,
                    "username":       username,
                    "amount":         amount,
                    "donation_date":  donation_date,
                    "added_by":       added_by,
                })
                .execute()
            )
        )
        rows = result or []
        return rows[0] if rows else None
    except Exception as exc:
        log.error(f"add_manual_donation({country_id}, {username}): {exc}")
        return None


async def delete_manual_donation(entry_id: int) -> bool:
    try:
        result = await asyncio.to_thread(
            lambda: (
                db_pool.table("manual_donations")
                .delete()
                .eq("id", entry_id)
                .execute()
            )
        )
        return bool(result)
    except Exception as exc:
        log.error(f"delete_manual_donation({entry_id}): {exc}")
        return False
