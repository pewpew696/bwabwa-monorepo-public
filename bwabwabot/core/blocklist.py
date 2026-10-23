# core/blocklist.py — blocklist generik (spy, cmd lain nanti)

from __future__ import annotations

import asyncio
import logging

from services.db import pool as db_pool

log = logging.getLogger("WarEraBot.blocklist")


async def is_blocked(table: str, key: str) -> bool:
    """Cek apakah `key` ada di blocklist `table`."""
    if not key:
        return False
    try:
        res = await asyncio.to_thread(
            lambda: db_pool.table(table).select("1").eq("player_id", key).execute()
        )
        return bool(res)
    except Exception as exc:
        log.error(f"is_blocked({table}, {key}): {exc}")
        return False


async def add_block(table: str, key: str, added_by: str, note: str = "") -> bool:
    """Tambah `key` ke blocklist. True kalau berhasil (atau sudah ada)."""
    if not key:
        return False
    try:
        await asyncio.to_thread(
            lambda: db_pool.table(table).upsert(
                {"player_id": key, "added_by": added_by, "note": note or None},
                on_conflict="player_id",
                ignore_duplicates=True,
            ).execute()
        )
        return True
    except Exception as exc:
        log.error(f"add_block({table}, {key}): {exc}")
        return False


async def remove_block(table: str, key: str) -> bool:
    """Hapus `key` dari blocklist. True kalau ada yang terhapus."""
    if not key:
        return False
    try:
        res = await asyncio.to_thread(
            lambda: db_pool.table(table).delete().eq("player_id", key).execute()
        )
        return bool(res)
    except Exception as exc:
        log.error(f"remove_block({table}, {key}): {exc}")
        return False


async def list_block(table: str) -> list[dict]:
    """Ambil semua entry blocklist."""
    try:
        res = await asyncio.to_thread(
            lambda: db_pool.table(table).select("*").order("added_at", desc=True).execute()
        )
        return list(res) if res else []
    except Exception as exc:
        log.error(f"list_block({table}): {exc}")
        return []


# --- wrapper spy ---
SPY_BLOCKLIST = "spy_blocklist"


async def is_player_blocked(player_id: str) -> bool:
    """Cek player ID diblok dari spy."""
    return await is_blocked(SPY_BLOCKLIST, player_id)
