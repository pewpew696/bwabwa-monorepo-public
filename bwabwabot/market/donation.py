# market/donation.py — fetch transaksi donasi + cache app_db
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from services.db import pool as db_pool

from .auth import _donation_auth_headers
from .client import _encode
from .constants import TRANSACTION_URL
from services.economy.donation import (
    get_week_range_start, aggregate_donations, group_donations_by_day,
)

log = logging.getLogger("WarEraBot.market")


DONATION_MAX_RETRIES   = 3
DONATION_RETRY_DELAY_S = 2
DONATION_MAX_PAGES     = 500


async def _fetch_donation_page(
    session: aiohttp.ClientSession, params: dict, page_num: int, log_prefix: str
) -> dict | None:
    """Fetch 1 halaman transaction (donation). Retry manual (fixed count +
    backoff linear), bukan _get_json_with_retry — respons endpoint ini bisa
    balikin list atau dict, jadi perlu baca raw text dulu baru json.loads
    manual sebelum unwrap result.data.

    Return None kalau semua percobaan gagal (caller yang urus fallback)."""
    url = f"{TRANSACTION_URL}?input={_encode(params)}"
    for attempt in range(DONATION_MAX_RETRIES):
        try:
            async with session.get(
                url, headers=_donation_auth_headers(), timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                r.raise_for_status()
                raw_text = await r.text()
            raw_json = json.loads(raw_text)
            if isinstance(raw_json, list):
                return raw_json[0].get("result", {}).get("data", {}) if raw_json else {}
            elif isinstance(raw_json, dict):
                return raw_json.get("result", {}).get("data", {})
            return {}
        except Exception as exc:
            log.warning(
                f"{log_prefix}: page {page_num} attempt {attempt + 1}/"
                f"{DONATION_MAX_RETRIES} gagal: {exc}"
            )
            if attempt + 1 < DONATION_MAX_RETRIES:
                await asyncio.sleep(DONATION_RETRY_DELAY_S * (attempt + 1))
    return None


async def fetch_donations(
    session: aiohttp.ClientSession, country_id: str, weeks: int = 1
) -> tuple[list[dict], bool]:
    cutoff_dt = get_week_range_start(weeks)
    cutoff    = cutoff_dt.isoformat().replace("+00:00", "Z")
    all_items: list[dict] = []
    cursor       = None
    _logged_keys = False
    complete     = True

    for page_num in range(DONATION_MAX_PAGES):
        params: dict = {"transactionType": "donation", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page_data = await _fetch_donation_page(session, params, page_num, "fetch_donations")

        if page_data is None:
            log.error(f"fetch_donations: halaman {page_num} gagal total setelah {DONATION_MAX_RETRIES}x retry.")
            complete = False
            break

        items       = page_data.get("items", [])
        next_cursor = page_data.get("nextCursor")
        if not _logged_keys and items:
            log.info(f"fetch_donations FIELD KEYS: {list(items[0].keys())}")
            _logged_keys = True

        stop = False
        for item in items:
            created = item.get("createdAt", "")
            if created < cutoff:
                stop = True
                break
            if item.get("sellerMuId"):
                continue
            if item.get("sellerCountryId") == country_id:
                all_items.append(item)

        if stop or not next_cursor or not items:
            break
        cursor = next_cursor
    else:
        log.warning(f"fetch_donations: mencapai batas {DONATION_MAX_PAGES} halaman, data mungkin tidak lengkap.")
        complete = False

    log.info(
        f"fetch_donations: {len(all_items)} results for country_id={country_id}, "
        f"weeks={weeks}, complete={complete}"
    )
    return all_items, complete


DONATION_SEED_WEEKS = 5


async def sync_donations_incremental(
    session: aiohttp.ClientSession, country_id: str
) -> tuple[int, bool]:
    """Samakan cache app_db dengan API: fetch dari transaksi terbaru, berhenti
    begitu ketemu transaksi yang udah tercatat di bookmark
    (donation_scan_state) — cuma transaksi baru sejak scan terakhir yang
    ditarik dari API.

    Kalau negara belum pernah discan (bookmark kosong), backfill penuh
    DONATION_SEED_WEEKS minggu ke belakang sekali ini aja, sesudahnya
    incremental.

    Return: (jumlah_transaksi_baru, complete). complete=False berarti scan
    berhenti krna kena safety cap halaman, bukan krna beneran caught up —
    akan disusul di panggilan berikutnya."""

    result = await asyncio.to_thread(
        lambda: db_pool.table("donation_scan_state").select("*").eq("country_id", country_id).execute()
    )
    state = result[0] if result else None
    bookmark_tx_id = state.get("last_tx_id") if state else None
    is_first_scan = state is None

    cutoff = None
    if is_first_scan:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(weeks=DONATION_SEED_WEEKS)
        cutoff = cutoff_dt.isoformat().replace("+00:00", "Z")

    new_rows: list[dict] = []
    newest_tx_id: Optional[str] = None
    newest_created_at: Optional[str] = None
    cursor = None
    complete = True

    for page_num in range(DONATION_MAX_PAGES):
        params: dict = {"transactionType": "donation", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page_data = await _fetch_donation_page(session, params, page_num, "sync_donations_incremental")

        if page_data is None:
            log.error(f"sync_donations_incremental({country_id}): halaman {page_num} gagal total, berhenti (partial).")
            complete = False
            break

        items       = page_data.get("items", [])
        next_cursor = page_data.get("nextCursor")

        if page_num == 0 and items:
            newest_tx_id      = items[0].get("_id")
            newest_created_at = items[0].get("createdAt")

        stop = False
        for item in items:
            tx_id = item.get("_id")
            if bookmark_tx_id and tx_id == bookmark_tx_id:
                stop = True
                break
            created = item.get("createdAt", "")
            if cutoff and created < cutoff:
                stop = True
                break
            if item.get("sellerMuId"):
                continue
            if item.get("sellerCountryId") != country_id:
                continue
            new_rows.append({
                "tx_id":      tx_id,
                "country_id": country_id,
                "buyer_id":   item.get("buyerId", ""),
                "money":      float(item.get("money", 0) or 0),
                "created_at": created,
            })

        if stop or not next_cursor or not items:
            break
        cursor = next_cursor
    else:
        log.warning(f"sync_donations_incremental({country_id}): mentok {DONATION_MAX_PAGES} halaman.")
        complete = False

    if new_rows:
        await asyncio.to_thread(
            lambda: db_pool.table("donation_transactions").upsert(
                new_rows, on_conflict="tx_id", ignore_duplicates=True
            ).execute()
        )
        if newest_tx_id:
            await asyncio.to_thread(
                lambda: db_pool.table("donation_scan_state").upsert(
                    {
                        "country_id": country_id,
                        "last_tx_id": newest_tx_id,
                        "last_created_at": newest_created_at,
                        "last_scanned_at": datetime.now(timezone.utc).isoformat(),
                    },
                    on_conflict="country_id",
                ).execute()
            )
    elif is_first_scan:
        await asyncio.to_thread(
            lambda: db_pool.table("donation_scan_state").upsert(
                {
                    "country_id": country_id,
                    "last_tx_id": "",
                    "last_created_at": None,
                    "last_scanned_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="country_id",
            ).execute()
        )

    log.info(
        f"sync_donations_incremental({country_id}): {len(new_rows)} transaksi baru, "
        f"complete={complete}, first_scan={is_first_scan}"
    )
    return len(new_rows), complete


async def get_cached_donations(country_id: str, since_iso: str) -> list[dict]:
    """Transaksi donasi dari cache app_db (bukan live API). Format output
    sama persis dengan fetch_donations() lama biar aggregate_donations() &
    group_donations_by_day() bisa dipakai tanpa perubahan."""

    result = await asyncio.to_thread(
        lambda: (
            db_pool.table("donation_transactions")
            .select("buyer_id, money, created_at")
            .eq("country_id", country_id)
            .gte("created_at", since_iso)
            .execute()
        )
    )
    rows = result or []
    return [
        {
            "buyerId":   r.get("buyer_id", ""),
            "money":     r.get("money", 0),
            "createdAt": r.get("created_at", ""),
        }
        for r in rows
    ]
