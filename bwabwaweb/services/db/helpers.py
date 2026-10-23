# services/db/helpers.py — helper DB stateless (dipindah dari main.py, Tahap 3 T3-6a)

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from services.db import pool as db_pool
from services.db.local import local_session

log = logging.getLogger("WarEraBot.db_helpers")


async def db_save_prices(prices: dict[str, float], volume: dict[str, dict] | None = None) -> None:
    """Simpan snapshot harga ke price_history.

    `volume` (opsional) = _volume_cache: {item_label: {"tx", "qty", "qty_h"}}.
    Dipakai buat ngisi kolom volume kalau datanya ada; kalau nggak ada (item
    baru / belum sempat di-refresh_volume) kolomnya NULL, bukan 0 — konsisten
    dengan makna "belum pernah dicatat"."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        volume = volume or {}
        rows = [
            {
                "item_name": k,
                "price": v,
                "recorded_at": now,
                "volume": volume.get(k, {}).get("qty"),
            }
            for k, v in prices.items()
        ]
        await asyncio.to_thread(
            lambda: db_pool.table("price_history").insert(rows).execute()
        )
        log.info(f"Supabase: {len(rows)} prices saved.")
    except Exception as exc:
        log.error(f"db_save_prices: {exc}")


async def db_save_snapshot(snap: dict, volume: dict[str, dict] | None = None) -> None:
    import math as _math
    volume = volume or {}
    ts = snap["ts"].isoformat()
    rows = []
    for k, price in snap["prices"].items():
        if not isinstance(price, (int, float)) or not _math.isfinite(price):
            continue
        r = snap["rows"].get(k) or {}
        rows.append({
            "item_name": k,
            "price": price,
            "recorded_at": ts,
            "volume": volume.get(k, {}).get("qty"),
            "bid": r.get("bid"),
            "ask": r.get("ask"),
            "mid": r.get("mid"),
            "bid_qty": r.get("bid_qty"),
            "ask_qty": r.get("ask_qty"),
        })
    if not rows:
        return
    try:
        await asyncio.to_thread(
            lambda: db_pool.table("price_history").insert(rows).execute()
        )
        log.info(f"price_history: {len(rows)} baris lengkap disimpan.")
    except Exception as exc:
        log.error(f"db_save_snapshot gagal ({exc}); fallback ke kolom lama")
        await db_save_prices(snap["prices"], volume)


async def db_get_history(item_name: str, hours: int = 720) -> list[dict]:
    """Ambil histori harga satu item dari PG lokal (app_db, via shim) — semua
    histori selalu ada di sana, tanpa batas retensi. Dipakai endpoint
    /api/item/<n> buat chart Order Book di web dashboard.

    PENTING: query descending + limit eksplisit, baru dibalik ke ascending.
    Kalau query ascending tanpa limit, PostgREST default cap ~1000 baris bakal
    motong dari yang PALING LAMA duluan — data terbaru malah kepotong kalau
    total baris dalam window > 1000 (item populer bisa >4000 baris/30 hari)."""
    now = datetime.now(timezone.utc)
    requested_cutoff = now - timedelta(hours=hours)

    rows: list[dict] = []
    try:
        result = await asyncio.to_thread(
            lambda: (
                db_pool.table("price_history")
                .select("price, recorded_at, volume")
                .eq("item_name", item_name)
                .gte("recorded_at", requested_cutoff.isoformat())
                .order("recorded_at", desc=True)
                .limit(6000)
                .execute()
            )
        )
        warm_rows = result or []
        warm_rows.reverse()  # balik jadi ascending (lama → baru) buat chart
        rows.extend(warm_rows)
    except Exception as exc:
        log.error(f"db_get_history({item_name}): supabase gagal — {exc}")

    return rows


async def db_save_volume_hourly(volume: dict[str, dict]) -> int:
    """Simpan bucket volume per jam dari hasil fetch_volume_24h_batched.

    `volume` = {item_label: {"tx", "qty", "qty_h", "by_hour": {datetime: qty}}}.
    Return jumlah baris di-upsert. ON CONFLICT (item_name, hour_start) DO UPDATE,
    jadi refresh berulang memperkaya bucket yang sama (window bergulir)."""
    rows: list[dict] = []
    for item_name, v in (volume or {}).items():
        by_hour = (v or {}).get("by_hour") or {}
        for hour_start, qty in by_hour.items():
            if qty is None or hour_start is None:
                continue
            rows.append({
                "item_name": item_name,
                "hour_start": hour_start,
                "qty": qty,
            })
    if not rows:
        return 0
    try:
        affected = await asyncio.to_thread(
            lambda: db_pool.table("price_volume_hourly")
                .upsert(rows, on_conflict="item_name, hour_start")
                .execute()
        )
        log.info(f"db_save_volume_hourly: {affected} baris di-upsert")
        return affected or 0
    except Exception as exc:
        log.error(f"db_save_volume_hourly: {exc}")
        return 0

async def db_save_bonus_snapshot(
    breakdown: dict[str, list[tuple[str, float]]],
    deposit_ends: dict[str, dict],
    tax_cache: dict[str, float],
) -> int:
    """Snapshot bonus + tax.

    - `breakdown` = {item_label: [(country_name, pct), ...]} (top 5 per item).
    - `deposit_ends` = {item_label: {country_name: ends_at}}.
    - `tax_cache` = {country_name: tax_pct}.

    `item_bonus_deposits` = REPLACE per item (snapshot top 5 sekarang).
    `country_tax_snapshot` = UPSERT (tax properti negara, bukan per item).
    Return total baris bonus yang di-insert.
    """
    if not breakdown:
        return 0

    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)

    bonus_rows: list[tuple] = []
    for item_name, entries in breakdown.items():
        ends_map = (deposit_ends or {}).get(item_name, {}) or {}
        for rank_no, (country_name, pct) in enumerate(entries, start=1):
            ends_at = ends_map.get(country_name)
            bonus_rows.append((item_name, country_name, float(pct), rank_no, ends_at, now))

    tax_rows: list[tuple] = []
    for country_name, tax_pct in (tax_cache or {}).items():
        if tax_pct is None:
            continue
        tax_rows.append((country_name, float(tax_pct), now))

    if not bonus_rows and not tax_rows:
        return 0

    try:
        def _run():
            with local_session(commit=True) as cur:
                if bonus_rows:
                    item_names = list(breakdown.keys())
                    cur.execute(
                        "DELETE FROM item_bonus_deposits WHERE item_name = ANY(%s)",
                        (item_names,),
                    )
                    cur.executemany(
                        """
                        INSERT INTO item_bonus_deposits
                            (item_name, country_name, pct, rank_no, ends_at, fetched_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        bonus_rows,
                    )
                if tax_rows:
                    cur.executemany(
                        """
                        INSERT INTO country_tax_snapshot
                            (country_name, tax_pct, fetched_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (country_name) DO UPDATE
                            SET tax_pct = EXCLUDED.tax_pct,
                                fetched_at = EXCLUDED.fetched_at
                        """,
                        tax_rows,
                    )
            return len(bonus_rows)

        affected = await asyncio.to_thread(_run)
        log.info(
            f"db_save_bonus_snapshot: {affected} bonus rows, "
            f"{len(tax_rows)} tax rows"
        )
        return affected
    except Exception as exc:
        log.error(f"db_save_bonus_snapshot: {exc}")
        return 0
