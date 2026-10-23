# market/user_tx.py — cache transaksi per-user (app_db)
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from services.db import pool as db_pool

from .auth import _auth_headers
from .client import _encode, _get_json_with_retry
from .constants import TRANSACTION_URL

log = logging.getLogger("WarEraBot.market")


USER_TX_TYPES = ("trading", "itemMarket", "craftItem", "battleLoot", "openCase", "dismantleItem")
_USER_TX_RAW_PAYLOAD_TYPES = {"craftItem", "battleLoot", "openCase", "dismantleItem"}
USER_TX_MAX_PAGES = 50
USER_TX_PAGE_LIMIT = 100


def _user_tx_to_row(item: dict, user_id: str, tx_type: str) -> dict:
    """Konversi 1 tx mentah API jadi baris siap-insert user_tx_raw. Kolom
    rata (item_code/quantity/dst) diisi kalau ada di payload aslinya.
    `raw` cuma diisi buat tipe yang datanya nested/rumit — trading/
    itemMarket dibiarkan NULL, gak perlu duplikasi."""
    return {
        "tx_id":              item.get("_id"),
        "user_id":            user_id,
        "tx_type":            tx_type,
        "created_at":         item.get("createdAt"),
        "item_code":          item.get("itemCode"),
        "quantity":           item.get("quantity"),
        "money":              item.get("money"),
        "buyer_id":           item.get("buyerId"),
        "seller_id":          item.get("sellerId"),
        "buyer_country_id":   item.get("buyerCountryId"),
        "seller_country_id":  item.get("sellerCountryId"),
        "raw":                item if tx_type in _USER_TX_RAW_PAYLOAD_TYPES else None,
    }


async def _sync_user_tx_one_type(
    session: aiohttp.ClientSession, user_id: str, tx_type: str, headers: Optional[dict] = None
) -> tuple[list[dict], bool]:
    """Sync 1 tipe transaksi buat 1 user, sampai ketemu bookmark lama atau
    caught up. Return (baris_baru, capped).

    headers: token API, default None = _auth_headers() (token bot biasa).
    Caller yang punya kuota terpisah (hub_intel C4) wajib kirim headers
    sendiri lewat sync_user_tx_incremental(..., headers=market._hub_auth_headers()),
    biar sync-nya gak numpang kuota token bot Discord."""

    result = await asyncio.to_thread(
        lambda: (
            db_pool.table("user_tx_sync_state")
            .select("bookmark_tx_id")
            .eq("user_id", user_id)
            .eq("tx_type", tx_type)
            .execute()
        )
    )
    bookmark_tx_id = result[0]["bookmark_tx_id"] if result else None
    is_first_scan = bookmark_tx_id is None
    req_headers = headers or _auth_headers()

    new_rows: list[dict] = []
    newest_tx_id: str | None = None
    newest_created_at: str | None = None
    cursor = None
    capped = False

    for page_num in range(USER_TX_MAX_PAGES):
        params: dict = {"userId": user_id, "transactionType": tx_type, "limit": USER_TX_PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        url = f"{TRANSACTION_URL}?input={_encode(params)}"

        try:
            resp = await _get_json_with_retry(session, url, headers=req_headers, timeout=15)
            data = resp["result"]["data"]
        except Exception as exc:
            log.error(f"_sync_user_tx_one_type({user_id}, {tx_type}): halaman {page_num} gagal — {exc!r}, berhenti (partial).")
            capped = True
            break

        items = data.get("items", [])
        if not items:
            break

        if page_num == 0:
            newest_tx_id = items[0].get("_id")
            newest_created_at = items[0].get("createdAt")

        stop = False
        for item in items:
            tx_id = item.get("_id")
            if bookmark_tx_id and tx_id == bookmark_tx_id:
                stop = True
                break
            new_rows.append(_user_tx_to_row(item, user_id, tx_type))

        next_cursor = data.get("nextCursor")
        if stop or not next_cursor:
            break
        cursor = next_cursor
        await asyncio.sleep(0.5)
    else:
        capped = True

    if newest_tx_id:
        await asyncio.to_thread(
            lambda: db_pool.table("user_tx_sync_state").upsert(
                {
                    "user_id": user_id,
                    "tx_type": tx_type,
                    "bookmark_tx_id": newest_tx_id,
                    "bookmark_created_at": newest_created_at,
                    "last_synced_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="user_id,tx_type",
            ).execute()
        )
    elif is_first_scan:
        await asyncio.to_thread(
            lambda: db_pool.table("user_tx_sync_state").upsert(
                {
                    "user_id": user_id,
                    "tx_type": tx_type,
                    "bookmark_tx_id": "",
                    "bookmark_created_at": None,
                    "last_synced_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="user_id,tx_type",
            ).execute()
        )

    return new_rows, capped
async def sync_user_tx_incremental(
    session: aiohttp.ClientSession, user_id: str, headers: Optional[dict] = None
) -> dict:
    """Sync semua tipe transaksi (USER_TX_TYPES) buat 1 user_id, dari API ke
    cache app_db (user_tx_raw). Incremental per tipe (bookmark tx_id).

    Dipanggil di awal xspy trade / xspy pl / hub_intel C4, sebelum baca
    cache lewat get_user_tx_cache() — biar cache selalu up-to-date pas mau
    dipakai reprocessing.

    headers: default None = token bot biasa (_auth_headers()), dipake xspy
    trade & xspy pl. hub_intel C4 wajib kirim headers=market._hub_auth_headers()
    biar sync-nya pake kuota token hub sendiri, bukan numpang bot Discord.

    Return: {"new_count": int, "capped": bool}"""

    total_new = 0
    any_capped = False

    for tx_type in USER_TX_TYPES:
        try:
            rows, capped = await _sync_user_tx_one_type(session, user_id, tx_type, headers=headers)
        except Exception as exc:
            log.error(f"sync_user_tx_incremental({user_id}, {tx_type}): gagal total — {exc!r}")
            any_capped = True
            continue

        if rows:
            await asyncio.to_thread(
                lambda: db_pool.table("user_tx_raw").upsert(
                    rows, on_conflict="tx_id", ignore_duplicates=True
                ).execute()
            )
        total_new += len(rows)
        any_capped = any_capped or capped

    if total_new:
        log.info(f"sync_user_tx_incremental({user_id}): +{total_new} transaksi baru dicache.")
    return {"new_count": total_new, "capped": any_capped}


async def get_user_tx_cache(
    user_id: str, tx_type: str | None = None, since: str | None = None
) -> list[dict]:
    """Baca cache user_tx_raw, format field API-style (_id/createdAt/itemCode/
    dst) biar kompatibel dengan kode reprocessing lama."""

    def _query():
        q = db_pool.table("user_tx_raw").select("*").eq("user_id", user_id)
        if tx_type:
            q = q.eq("tx_type", tx_type)
        if since:
            q = q.gte("created_at", since)
        return q.execute()

    result = await asyncio.to_thread(_query)
    rows = result or []

    out = []
    for r in rows:
        item = {
            "_id":               r.get("tx_id"),
            "createdAt":         r.get("created_at"),
            "transactionType":   r.get("tx_type"),
            "itemCode":          r.get("item_code"),
            "quantity":          r.get("quantity"),
            "money":             r.get("money"),
            "buyerId":           r.get("buyer_id"),
            "sellerId":          r.get("seller_id"),
            "buyerCountryId":    r.get("buyer_country_id"),
            "sellerCountryId":   r.get("seller_country_id"),
        }
        if r.get("raw"):
            item.update(r["raw"])
        out.append(item)
    return out
