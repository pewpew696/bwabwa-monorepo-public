# territory_tax_collector.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import aiohttp

import market as mkt
from services.territory import tax_store as store
from services.territory.tax_store import TAX_RATE_TTL_HOURS

log = logging.getLogger("WarEraBot.territory_tax_collector")

WAGE_PAGE_LIMIT = 100
WAGE_MAX_PAGES = 500  # safety cap per run, sama pola DONATION_MAX_PAGES

# TTL cache
CITIZENSHIP_TTL_DAYS = 30    # match cooldown ganti kewarganegaraan in-game
BUYER_SCAN_TTL_HOURS = 5
PROCESSING_CONCURRENCY = 25  # batas paralel Pass 1 & Pass 2 (dedup buyer, matching event)

# Timeout keras API WarEra — cegah gather nyangkut.
EXTERNAL_CALL_TIMEOUT_SECONDS = 90

# split pajak income (flat, tanpa syarat foreign worker)
INCOME_TAX_SPLIT_OPERATING = 0.70  # ke negara operasi company
INCOME_TAX_SPLIT_WORKER = 0.30     # ke negara asal (kewarganegaraan) worker


def _auth_headers() -> dict:
    """Reuse WARERA_API_KEY_HUB, bukan bikin token dedicated baru."""
    return mkt._hub_auth_headers()


# --- 1. fetch wage feed global (incremental, pola sama sync_donations_incremental) ---

async def fetch_new_wage_events(session: aiohttp.ClientSession) -> tuple[list[dict], str | None, str | None]:
    """Tarik wage terbaru dari feed global, stop saat tx_id ada di bookmark."""
    state = await asyncio.to_thread(store.get_scan_state)
    bookmark_tx_id = state.get("last_tx_id") if state else None

    new_items: list[dict] = []
    newest_tx_id: str | None = None
    newest_created_at: str | None = None
    cursor = None

    for page_num in range(WAGE_MAX_PAGES):
        params: dict = {"transactionType": "wage", "limit": WAGE_PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor

        url = f"{mkt.TRANSACTION_URL}?input={mkt._encode(params)}"
        try:
            resp = await asyncio.wait_for(
                mkt._get_json_with_retry(session, url, headers=_auth_headers(), timeout=15),
                timeout=EXTERNAL_CALL_TIMEOUT_SECONDS,
            )
            data = resp["result"]["data"]
        except asyncio.TimeoutError:
            log.error(
                f"fetch_new_wage_events: TIMEOUT setelah {EXTERNAL_CALL_TIMEOUT_SECONDS}s "
                f"-- halaman {page_num} (cursor={cursor}) -- berhenti (partial)"
            )
            break
        except Exception as exc:
            log.error(f"fetch_new_wage_events: halaman {page_num} gagal total ({exc!r}), berhenti (partial).")
            break

        items = data.get("items", [])
        next_cursor = data.get("nextCursor")

        if page_num == 0 and items:
            newest_tx_id = items[0].get("_id")
            newest_created_at = items[0].get("createdAt")

        stop = False
        for item in items:
            tx_id = item.get("_id")
            if bookmark_tx_id and tx_id == bookmark_tx_id:
                stop = True
                break
            new_items.append(item)

        if stop or not next_cursor or not items:
            break
        cursor = next_cursor
    else:
        log.warning(f"fetch_new_wage_events: mentok {WAGE_MAX_PAGES} halaman, kemungkinan belum sampai bookmark.")

    log.info(f"fetch_new_wage_events: {len(new_items)} transaksi wage baru.")
    return new_items, newest_tx_id, newest_created_at


# --- 2. enrichment: cocokkan wage transaction -> company ---

async def _get_worker_snapshot(session: aiohttp.ClientSession, company_id: str) -> list[dict]:
    """Cache-first: cek territory_worker_snapshots dulu, fallback fetch API."""
    cached = await asyncio.to_thread(store.get_cached_worker_snapshot, company_id)
    if cached is not None:
        return cached

    try:
        workers = await asyncio.wait_for(
            mkt.fetch_workers(session, company_id),
            timeout=EXTERNAL_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.error(
            f"_get_worker_snapshot: TIMEOUT setelah {EXTERNAL_CALL_TIMEOUT_SECONDS}s "
            f"-- mkt.fetch_workers(company_id={company_id}) -- return [] (unresolved)"
        )
        return []
    except Exception as exc:
        log.error(f"_get_worker_snapshot(company_id={company_id}): fetch_workers gagal ({exc!r})")
        return []

    await asyncio.to_thread(store.save_worker_snapshot_batch, company_id, workers)
    return [
        {"user_id": w.get("user"), "employer_id": w.get("employer"),
         "wage": w.get("wage"), "joined_at": w.get("joinedAt"), "raw_payload": w}
        for w in workers
    ]


async def find_company_for_wage(
    session: aiohttp.ClientSession, seller_id: str, buyer_id: str,
    money: float, created_at: str,
) -> tuple[str | None, str]:
    """Cari company_id buat 1 wage tx (buyer_id == company owner)."""
    from services.spy import cache_store as spy_store
    try:
        rows = await asyncio.to_thread(spy_store.get_companies_by_owner, buyer_id)
        candidates = [row["company_id"] for row in rows]
    except Exception as exc:
        log.error(f"find_company_for_wage: query company_index gagal ({exc!r})")
        candidates = []

    if not candidates:
        return None, "unresolved"

    for company_id in candidates:
        workers = await _get_worker_snapshot(session, company_id)
        for w in workers:
            if w.get("user_id") != seller_id:
                continue
            joined_at = w.get("joined_at")
            if joined_at and joined_at > created_at:
                continue
            return company_id, "worker_snapshot"
    return None, "unresolved"


async def _fetch_worker_citizenship(session: aiohttp.ClientSession, user_id: str) -> str | None:
    """getUserLite -> field 'country'."""
    url = f"{mkt.USER_LITE_URL}?input={mkt._encode({'userId': user_id})}"
    try:
        resp = await asyncio.wait_for(
            mkt._get_json_with_retry(session, url, headers=_auth_headers(), timeout=10),
            timeout=EXTERNAL_CALL_TIMEOUT_SECONDS,
        )
        data = resp["result"]["data"]
        return data.get("country")
    except asyncio.TimeoutError:
        log.error(
            f"_fetch_worker_citizenship: TIMEOUT setelah {EXTERNAL_CALL_TIMEOUT_SECONDS}s "
            f"-- user_id={user_id} -- return None"
        )
        return None
    except Exception as exc:
        log.error(f"_fetch_worker_citizenship({user_id}): gagal ({exc!r})")
        return None


async def _resolve_operating_country(session: aiohttp.ClientSession, company_id: str) -> tuple[str | None, str | None]:
    """company_id -> (region_id, operating_country_id)."""
    from services.spy import cache_store as spy_store
    try:
        region_id = await asyncio.to_thread(spy_store.get_company_region, company_id)
    except Exception as exc:
        log.error(f"_resolve_operating_country({company_id}): query company_index gagal ({exc!r})")
        region_id = None

    if not region_id:
        return None, None

    try:
        _, regions_obj = await asyncio.wait_for(
            mkt.get_bonus_raw_data(session, with_cache=True),
            timeout=EXTERNAL_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.error(
            f"_resolve_operating_country: TIMEOUT setelah {EXTERNAL_CALL_TIMEOUT_SECONDS}s "
            f"-- mkt.get_bonus_raw_data(company_id={company_id}, region_id={region_id}) "
            f"-- return ({region_id!r}, None)"
        )
        return region_id, None
    except Exception as exc:
        log.error(f"_resolve_operating_country({company_id}): gagal ambil regions_obj ({exc!r})")
        return region_id, None

    region_data = regions_obj.get(region_id) if isinstance(regions_obj, dict) else None
            # Country ID ada di key 'country' (verified manual).
    country_id = region_data.get("country") if isinstance(region_data, dict) else None
    return region_id, country_id


async def _fetch_country_tax_rate(session: aiohttp.ClientSession, country_id: str) -> dict | None:
    """getCountryById -> field 'taxes'."""
    try:
        detail = await asyncio.wait_for(
            mkt.fetch_country_by_id(session, country_id, rate_limiter=mkt._tax_limiter),
            timeout=EXTERNAL_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.error(
            f"_fetch_country_tax_rate: TIMEOUT setelah {EXTERNAL_CALL_TIMEOUT_SECONDS}s "
            f"-- mkt.fetch_country_by_id(country_id={country_id}) -- return None"
        )
        return None
    except Exception as exc:
        log.error(f"_fetch_country_tax_rate({country_id}): gagal ({exc!r})")
        return None

    if not detail:
        return None
    taxes = detail.get("taxes") or {}
    return {
        "income_rate": taxes.get("income"),
        "market_rate": taxes.get("market"),
        "selfwork_rate": taxes.get("selfWork"),
    }


# --- 3. orkestrasi: fetch -> enrich -> hitung pajak -> tulis event ---

async def run_collector_once(session: aiohttp.ClientSession) -> int:
    """Satu siklus: fetch, enrich, hitung pajak, tulis."""
    raw_items, newest_tx_id, newest_created_at = await fetch_new_wage_events(session)
    if not raw_items:
        return 0

    # --- Pass 1: dedup buyer_id, skip TTL fresh. Concurrent via Semaphore. ---
    unique_buyer_ids = list({item.get("buyerId", "") for item in raw_items if item.get("buyerId")})
    buyer_ttl = timedelta(hours=BUYER_SCAN_TTL_HOURS)
    now = datetime.now(timezone.utc)
    buyer_sem = asyncio.Semaphore(PROCESSING_CONCURRENCY)

    async def _refresh_buyer_if_stale(buyer_id: str) -> None:
        async with buyer_sem:
            last_scan = await asyncio.to_thread(store.get_buyer_last_scan, buyer_id)
            if last_scan and (now - last_scan) < buyer_ttl:
                return  # masih fresh, skip fetch API
            try:
                await asyncio.wait_for(
                    mkt.fetch_and_cache_user_companies(session, buyer_id),
                    timeout=EXTERNAL_CALL_TIMEOUT_SECONDS,
                )
                await asyncio.to_thread(store.save_buyer_scan_state, buyer_id)
            except asyncio.TimeoutError:
                log.error(
                    f"run_collector_once: TIMEOUT setelah {EXTERNAL_CALL_TIMEOUT_SECONDS}s "
                    f"-- mkt.fetch_and_cache_user_companies(buyer_id={buyer_id}) -- "
                    f"lanjut, matching untuk buyer ini bakal pakai company_index yang ada"
                )
            except Exception as exc:
                log.error(
                    f"run_collector_once: fetch_and_cache_user_companies gagal utk "
                    f"buyer_id={buyer_id} ({exc!r}) -- lanjut, matching untuk buyer "
                    f"ini bakal pakai company_index yang ada (mungkin belum lengkap "
                    f"kalau ini buyer baru pertama kali muncul)."
                )

    if unique_buyer_ids:
        await asyncio.gather(*[_refresh_buyer_if_stale(b) for b in unique_buyer_ids])
    log.info(f"run_collector_once: Pass 1 selesai -- {len(unique_buyer_ids)} buyer_id unik diperiksa.")

    # --- Pass 2: resolve company+region+country, concurrent. ---
    match_sem = asyncio.Semaphore(PROCESSING_CONCURRENCY)

    async def _process_item(item: dict) -> dict:
        seller_id = item.get("sellerId", "")
        buyer_id = item.get("buyerId", "")
        money = float(item.get("money", 0) or 0)
        created_at = item.get("createdAt", "")

        row = {
            "tx_id": item.get("_id"),
            "created_at": created_at,
            "updated_at": item.get("updatedAt"),
            "money": money,
            "seller_id": seller_id,
            "buyer_id": buyer_id,
            "raw_payload": item,
        }

        async with match_sem:
            try:
                company_id, match_method = await find_company_for_wage(
                    session, seller_id, buyer_id, money, created_at
                )
            except Exception as exc:
                log.error(f"run_collector_once: matching gagal utk tx {row['tx_id']} ({exc!r})")
                company_id, match_method = None, "unresolved"

            row["company_id"] = company_id
            row["match_method"] = match_method

            if company_id:
                region_id, operating_country_id = await _resolve_operating_country(session, company_id)
                row["operating_region_id"] = region_id
                row["operating_country_id"] = operating_country_id

        return row

    rows = await asyncio.gather(*[_process_item(item) for item in raw_items])
    rows = list(rows)
    log.info(f"run_collector_once: Pass 2 selesai -- {len(rows)} event di-resolve.")

    # --- Pass 3: batch citizenship+tax, concurrent untuk cache-miss. ---
    resolved = [r for r in rows if r.get("company_id")]
    unique_sellers = list({r["seller_id"] for r in resolved})
    unique_countries = list({r["operating_country_id"] for r in resolved if r.get("operating_country_id")})

    citizenship_map = await asyncio.to_thread(store.get_citizenship_cached, unique_sellers, CITIZENSHIP_TTL_DAYS)
    missing_sellers = [s for s in unique_sellers if s not in citizenship_map]
    if missing_sellers:
        fetched = await asyncio.gather(*[_fetch_worker_citizenship(session, s) for s in missing_sellers])
        new_citizenship_rows = [
            {"seller_id": s, "country_id": c} for s, c in zip(missing_sellers, fetched) if c
        ]
        await asyncio.to_thread(store.upsert_citizenship_batch, new_citizenship_rows)
        citizenship_map.update({r["seller_id"]: r["country_id"] for r in new_citizenship_rows})

    # Owner citizenship: buyer_id pakai cache + API yang sama (satu user satu negara).
    unique_buyers = list({r["buyer_id"] for r in resolved if r.get("buyer_id")})
    owner_map = await asyncio.to_thread(store.get_citizenship_cached, unique_buyers, CITIZENSHIP_TTL_DAYS)
    missing_buyers = [b for b in unique_buyers if b not in owner_map]
    if missing_buyers:
        fetched_o = await asyncio.gather(*[_fetch_worker_citizenship(session, b) for b in missing_buyers])
        new_owner_rows = [
            {"seller_id": b, "country_id": c} for b, c in zip(missing_buyers, fetched_o) if c
        ]
        await asyncio.to_thread(store.upsert_citizenship_batch, new_owner_rows)
        owner_map.update({r["seller_id"]: r["country_id"] for r in new_owner_rows})
    log.info(f"run_collector_once: Pass 3 selesai -- {len(owner_map)} owner citizenship resolved.")

    tax_rate_map = await asyncio.to_thread(store.get_tax_rate_cached, unique_countries, TAX_RATE_TTL_HOURS)
    missing_countries = [c for c in unique_countries if c not in tax_rate_map]
    if missing_countries:
        fetched = await asyncio.gather(*[_fetch_country_tax_rate(session, c) for c in missing_countries])
        new_rate_rows = [
            {"country_id": c, **rate} for c, rate in zip(missing_countries, fetched) if rate
        ]
        await asyncio.to_thread(store.upsert_tax_rate_batch, new_rate_rows)
        tax_rate_map.update({r["country_id"]: r for r in new_rate_rows})

    # --- Pass 4: gabungkan hasil, hitung pajak per event ---
    for row in rows:
        if not row.get("company_id"):
            continue

        worker_country_id = citizenship_map.get(row["seller_id"])
        operating_country_id = row.get("operating_country_id")
        rate_info = tax_rate_map.get(operating_country_id) if operating_country_id else None

        row["worker_citizenship_country_id"] = worker_country_id
        row["owner_citizenship_country_id"] = owner_map.get(row["buyer_id"])
        row["is_foreign_worker"] = (
            bool(worker_country_id and operating_country_id and worker_country_id != operating_country_id)
            if (worker_country_id and operating_country_id) else None
        )

        income_rate = rate_info.get("income_rate") if rate_info else None
        if income_rate is not None:
            # Asumsi income_rate persen. Kalau desimal, hapus '/100' ini.
            gross_tax = row["money"] * float(income_rate) / 100
            row["income_tax_rate"] = income_rate
            row["gross_tax"] = gross_tax
            row["tax_to_operating_country"] = gross_tax * INCOME_TAX_SPLIT_OPERATING
            row["tax_to_worker_country"] = gross_tax * INCOME_TAX_SPLIT_WORKER

        row["enriched_at"] = datetime.now(timezone.utc).isoformat()

    write_ok = await asyncio.to_thread(store.save_wage_events_batch, rows)
    if write_ok:
        # Bookmark disave cuma kalau DB sukses.
        if newest_tx_id:
            await asyncio.to_thread(store.save_scan_state, newest_tx_id, newest_created_at)
        log.info(
            f"run_collector_once: {len(rows)} event ditulis "
            f"({sum(1 for r in rows if r['company_id'])} enriched)."
        )

        touched_dates = sorted({
            r["created_at"][:10]
            for r in rows
            if r.get("company_id") and r.get("gross_tax") is not None and r.get("created_at")
        })
        if touched_dates:
            try:
                rollup_ok = await asyncio.to_thread(store.recalculate_daily_wage_rollup, touched_dates)
                if not rollup_ok:
                    log.error(
                        f"run_collector_once: recalculate_daily_wage_rollup gagal sebagian "
                        f"utk tanggal {touched_dates} -- rollup bisa stale, dicoba lagi siklus berikutnya."
                    )
            except Exception as exc:
                log.error(
                    f"run_collector_once: recalculate_daily_wage_rollup error total "
                    f"({exc!r}) utk tanggal {touched_dates} -- rollup tidak ter-update siklus ini."
                )
            # Rollup per-country per-jam buat dashboard Fiscal Monitor.
            try:
                from services.territory import fiscal_rollup as hroll

                touched_hours = hroll.touched_hours_from_rows(rows)
                if touched_hours:
                    h_ok = await asyncio.to_thread(hroll.recalculate_hourly_fiscal, touched_hours)
                    if not h_ok:
                        log.error("run_collector_once: hourly_country_tax gagal — dicoba siklus berikutnya.")
                    # Breakdown per region/owner/item buat drilldown country.
                    try:
                        from services.territory import fiscal_breakdown_rollup as broll

                        b_ok = await asyncio.to_thread(broll.recalculate_hourly_fiscal_breakdown, touched_hours)
                        if not b_ok:
                            log.error("run_collector_once: breakdown gagal — dicoba siklus berikutnya.")
                    except Exception as bexc:
                        log.error(f"run_collector_once: breakdown error ({bexc!r}) — lanjut.")
            except Exception as exc:
                log.error(f"run_collector_once: hourly_country_tax error ({exc!r}) — lanjut.")
    else:
        log.error(
            f"run_collector_once: save_wage_events_batch GAGAL untuk {len(rows)} event -- "
            f"bookmark TIDAK disave, batch ini bakal di-fetch ulang siklus berikutnya."
        )
    return len(rows)


async def backfill_owner_citizenship(
    session: aiohttp.ClientSession, batch_limit: int = 500, max_batches: int = 0,
) -> int:
    """Backfill owner_citizenship_country_id untuk event lama.

    Ambil distinct buyer_id yang NULL, resolve via cache/API, update batch.
    Idempotent — aman dijalankan ulang. max_batches=0 berarti tanpa batas.
    Return total baris ter-update.
    """
    total = 0
    batches = 0
    while True:
        buyer_ids = await asyncio.to_thread(store.get_buyers_missing_owner_citizenship, batch_limit)
        if not buyer_ids:
            break
        cmap = await asyncio.to_thread(store.get_citizenship_cached, buyer_ids, CITIZENSHIP_TTL_DAYS)
        missing = [b for b in buyer_ids if b not in cmap]
        if missing:
            fetched = await asyncio.gather(*[_fetch_worker_citizenship(session, b) for b in missing])
            new_rows = [{"seller_id": b, "country_id": c} for b, c in zip(missing, fetched) if c]
            await asyncio.to_thread(store.upsert_citizenship_batch, new_rows)
            cmap.update({r["seller_id"]: r["country_id"] for r in new_rows})
        upd_rows = [{"buyer_id": b, "country_id": cmap[b]} for b in buyer_ids if b in cmap]
        # Tandai yang tidak ketemu biar tidak diulang terus: set '' (bukan NULL).
        no_country = [b for b in buyer_ids if b not in cmap]
        if no_country:
            # Simpan string kosong = sudah dicoba, tidak ada data.
            await asyncio.to_thread(
                store.update_owner_citizenship_batch,
                [{"buyer_id": b, "country_id": ""} for b in no_country],
            )
        updated = await asyncio.to_thread(store.update_owner_citizenship_batch, upd_rows)
        total += updated
        batches += 1
        log.info(f"backfill_owner_citizenship: batch {batches} -- {updated} baris.")
        if max_batches and batches >= max_batches:
            break
    log.info(f"backfill_owner_citizenship: selesai -- {total} baris total.")
    return total
