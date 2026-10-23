# market/companies.py — company scan pipeline (orchestrator)
from __future__ import annotations

import asyncio
import logging

import aiohttp
from services.db import pool as db_pool

from .activity import fetch_workers
from .auth import (
    _auth_headers,
    _detail1_auth_headers,
    _detail2_auth_headers,
    _donation_auth_headers,
    _paginate_auth_headers,
)
from .client import _encode, _get_json_with_retry
from .companies_helpers import (
    COMPANY_BATCH_SIZE,
    _company_row_from_detail,
    _run_detail_chunks,
)
from .constants import COMPANIES_URL
from .rate_limit import (
    _detail1_limiter,
    _detail2_limiter,
    _paginate_limiter,
)

log = logging.getLogger("WarEraBot.market")


COMPANY_SCAN_MAX_PAGES = 15000


COMPANY_FLUSH_GROUP_SIZE = 1000


async def _fetch_companies_detail_group(
    session: aiohttp.ClientSession, company_ids: list[str]
) -> dict[str, dict]:
    """Fetch detail buat 1 grup company (ukuran COMPANY_FLUSH_GROUP_SIZE),
    dibagi ke 2 worker paralel (token DETAIL1 + DETAIL2). Chunk yang gagal
    di percobaan pertama di-retry sekali lagi di akhir grup (token
    PAGINATE) sebelum bener-bener dianggap gagal."""
    if not company_ids:
        return {}
    chunks = [
        company_ids[i:i + COMPANY_BATCH_SIZE]
        for i in range(0, len(company_ids), COMPANY_BATCH_SIZE)
    ]
    mid = len(chunks) // 2
    chunks1, chunks2 = chunks[:mid], chunks[mid:]

    (out1, failed1), (out2, failed2) = await asyncio.gather(
        _run_detail_chunks(session, chunks1, _detail1_auth_headers(), _detail1_limiter, "DETAIL1"),
        _run_detail_chunks(session, chunks2, _detail2_auth_headers(), _detail2_limiter, "DETAIL2"),
    )
    out = {**out1, **out2}
    total_chunks1, total_chunks2 = len(chunks1), len(chunks2)
    ok1, ok2 = total_chunks1 - len(failed1), total_chunks2 - len(failed2)

    if total_chunks1 > 0 and ok1 == 0 and ok2 > 0:
        log.error(
            f"_fetch_companies_detail_group: worker DETAIL1 GAGAL TOTAL "
            f"({total_chunks1} chunk, 0 sukses) — cek WARERA_API_KEY_DETAIL1. "
            f"Reroute sisa chunk-nya ke DETAIL2."
        )
        rerouted, failed1 = await _run_detail_chunks(
            session, chunks1, _detail2_auth_headers(), _detail2_limiter, "DETAIL2(reroute-dari-1)"
        )
        out.update(rerouted)
    elif total_chunks2 > 0 and ok2 == 0 and ok1 > 0:
        log.error(
            f"_fetch_companies_detail_group: worker DETAIL2 GAGAL TOTAL "
            f"({total_chunks2} chunk, 0 sukses) — cek WARERA_API_KEY_DETAIL2. "
            f"Reroute sisa chunk-nya ke DETAIL1."
        )
        rerouted, failed2 = await _run_detail_chunks(
            session, chunks2, _detail1_auth_headers(), _detail1_limiter, "DETAIL1(reroute-dari-2)"
        )
        out.update(rerouted)
    elif ok1 == 0 and ok2 == 0 and (total_chunks1 + total_chunks2) > 0:
        log.error(
            "_fetch_companies_detail_group: KEDUA worker (DETAIL1 & DETAIL2) GAGAL "
            "TOTAL — kemungkinan bukan soal token, tapi endpoint/jaringan WarEra "
            "lagi bermasalah. Tidak ada worker sehat buat reroute."
        )

    remaining_failed = failed1 + failed2
    if remaining_failed:
        log.warning(
            f"_fetch_companies_detail_group: {len(remaining_failed)} chunk gagal "
            f"di percobaan pertama, retry sekali lagi (token PAGINATE)..."
        )
        retry_out, still_failed = await _run_detail_chunks(
            session, remaining_failed, _paginate_auth_headers(), _paginate_limiter, "RETRY"
        )
        out.update(retry_out)
        if still_failed:
            log.error(
                f"_fetch_companies_detail_group: {len(still_failed)} chunk TETAP "
                f"gagal setelah retry — company di dalamnya bakal ke-refresh di "
                f"cycle scan berikutnya (bukan hilang dari tabel, cuma belum ke-update)."
            )
    else:
        log.info(
            f"_fetch_companies_detail_group: DETAIL1={ok1}/{total_chunks1} chunk, "
            f"DETAIL2={ok2}/{total_chunks2} chunk sukses (percobaan pertama)."
        )

    return out


COMPANY_USER_FETCH_MAX_PAGES = 50


async def fetch_and_cache_user_companies(
    session: aiohttp.ClientSession, user_id: str,
) -> list[dict]:
    """On-demand live fetch company milik 1 user_id, bukan full-scan. Dipake
    xspy player & territory_tax_collector.py, gantiin strategi lama (baca-
    only dari cache hasil background scan fetch_all_companies_index).

    Beda dari fetch_all_companies_index: fungsi itu sengaja gak kirim param
    userId krna dulu dikira filter server-side gak jalan. Udah diverifikasi
    ulang manual — tanpa filter dapet 100 items/halaman, dengan userId=<id>
    dapet 12 items (cocok jumlah company user). Filter ini beneran aktif di
    endpoint asli.

    Algoritma:
      1. Paginate company.getCompanies dengan userId+perPage+cursor, kumpulkan
         company ID (dedup, safety cap COMPANY_USER_FETCH_MAX_PAGES).
      2. response items berupa array of string ID, detail lengkap diambil
         terpisah lewat _fetch_companies_detail_group (reuse dari full-scan).
      3. Upsert ke app_db lewat spy_cache_store.upsert_companies_batch.

    Return: list row (shape _company_row_from_detail) yang berhasil di-upsert.
    Kosong kalau user gak punya company / fetch gagal total di halaman pertama."""
    from services.spy import cache_store as spy_store

    all_ids: list[str] = []
    seen_ids: set[str] = set()
    cursor = None

    for _ in range(COMPANY_USER_FETCH_MAX_PAGES):
        params: dict = {"userId": user_id, "perPage": 100}
        if cursor:
            params["cursor"] = cursor
        url = f"{COMPANIES_URL}?input={_encode(params)}"
        try:
            result = await _get_json_with_retry(session, url, headers=_auth_headers(), timeout=15)
            data = result["result"]["data"]
        except Exception as exc:
            log.error(
                f"fetch_and_cache_user_companies({user_id}): GAGAL TOTAL setelah "
                f"retry ({exc!r}) — berhenti, {len(all_ids)} ID yang sempat "
                f"terkumpul tetap dipakai (partial)."
            )
            break

        items = data.get("items", [])
        next_cursor = data.get("nextCursor")

        for i in items:
            if i not in seen_ids:
                seen_ids.add(i)
                all_ids.append(i)

        if not next_cursor or not items:
            break
        cursor = next_cursor
    else:
        log.warning(
            f"fetch_and_cache_user_companies({user_id}): MENTOK safety cap "
            f"{COMPANY_USER_FETCH_MAX_PAGES} halaman — user ini kemungkinan "
            f"besar punya >{COMPANY_USER_FETCH_MAX_PAGES * 100} company "
            f"(sangat tidak biasa), data mungkin belum lengkap."
        )

    if not all_ids:
        return []

    details = await _fetch_companies_detail_group(session, all_ids)
    rows = [_company_row_from_detail(cid, d) for cid, d in details.items()]

    if rows:
        await asyncio.to_thread(spy_store.upsert_companies_batch, rows)

    return rows


COMPANY_OWNER_REFRESH_MAX_PAGES = 50


async def refresh_owner_companies(session: aiohttp.ClientSession, owner_id: str) -> dict:
    """Refresh company milik 1 owner_id (dipanggil per pemilik yang baru
    login, ganti scan company lama). Beda dari fetch_and_cache_user_companies:
    fungsi ini JUGA (1) pakai token DONATION (bukan token umum) dan
    (2) hapus company yang sudah tidak muncul lagi di hasil API (dibongkar
    pemilik) dari company_index + company_workers, dan (3) refresh worker
    per company ke tabel company_workers.

    Return dict ringkasan: {"fetched": int, "deleted": int, "workers_synced": int}.
    """
    from services.spy import cache_store as spy_store

    headers = _donation_auth_headers()

    old_rows = spy_store.get_companies_by_owner(owner_id)
    old_ids = {r["company_id"] for r in old_rows}

    all_ids: list[str] = []
    seen_ids: set[str] = set()
    cursor = None

    for _ in range(COMPANY_OWNER_REFRESH_MAX_PAGES):
        params: dict = {"userId": owner_id, "perPage": 100}
        if cursor:
            params["cursor"] = cursor
        url = f"{COMPANIES_URL}?input={_encode(params)}"
        try:
            result = await _get_json_with_retry(session, url, headers=headers, timeout=15)
            data = result["result"]["data"]
        except Exception as exc:
            log.error(
                f"refresh_owner_companies({owner_id}): GAGAL TOTAL setelah retry "
                f"({exc!r}) — berhenti, {len(all_ids)} ID yang sempat terkumpul "
                f"tetap dipakai (partial)."
            )
            break

        items = data.get("items", [])
        next_cursor = data.get("nextCursor")

        for i in items:
            if i not in seen_ids:
                seen_ids.add(i)
                all_ids.append(i)

        if not next_cursor or not items:
            break
        cursor = next_cursor
    else:
        log.warning(
            f"refresh_owner_companies({owner_id}): MENTOK safety cap "
            f"{COMPANY_OWNER_REFRESH_MAX_PAGES} halaman."
        )

    new_ids = set(all_ids)

    gone_ids = old_ids - new_ids
    deleted = 0
    if gone_ids:
        deleted = await asyncio.to_thread(spy_store.delete_companies_batch, list(gone_ids))
        await asyncio.to_thread(spy_store.delete_company_workers_batch, list(gone_ids))

    if not all_ids:
        return {"fetched": 0, "deleted": deleted, "workers_synced": 0}

    details = await _fetch_companies_detail_group(session, all_ids)
    rows = [_company_row_from_detail(cid, d) for cid, d in details.items()]
    if rows:
        await asyncio.to_thread(spy_store.upsert_companies_batch, rows)

    workers_synced = 0
    for cid in all_ids:
        try:
            workers = await fetch_workers(session, cid)
            n = await asyncio.to_thread(spy_store.upsert_company_workers, cid, workers)
            workers_synced += n
        except Exception as exc:
            log.error(f"refresh_owner_companies({owner_id}): worker sync gagal utk {cid} — {exc}")

    return {"fetched": len(all_ids), "deleted": deleted, "workers_synced": workers_synced}


async def fetch_all_companies_index(
    session: aiohttp.ClientSession,
    flush_callback=None,
    start_cursor: str | None = None,
) -> tuple[int, str | None]:
    """Full-scan semua company di game. Cuma dipanggil background job (tiap
    3 jam), jangan dipanggil live — bisa makan ratusan/ribuan API call.

    Hasil detail-fetch diflush bertahap per grup ~COMPANY_FLUSH_GROUP_SIZE
    lewat flush_callback(rows), bukan dikumpulin dulu semuanya baru ditulis
    di akhir — biar progress kesimpen bertahap, kalau proses mati di tengah
    hasil yang udah sukses tetep aman.

    Return: total company yang berhasil di-fetch & di-flush.

    company.getCompanies gak bisa difilter server-side (udah dikonfirmasi),
    jadi paginate semua company lalu filter per-negara dilakuin belakangan
    (di sisi command, pake cache ini + mapping region->country)."""
    all_ids: list[str] = []
    seen_ids: set[str] = set()
    cursor = start_cursor
    resume_cursor: str | None = None

    for _ in range(COMPANY_SCAN_MAX_PAGES):
        params: dict = {"cursor": cursor} if cursor else {}
        url = f"{COMPANIES_URL}?input={_encode(params)}"
        try:
            result = await _get_json_with_retry(
                session, url, headers=_paginate_auth_headers(), timeout=15,
                rate_limiter=_paginate_limiter,
            )
            data = result["result"]["data"]
        except Exception as exc:
            log.error(
                f"fetch_all_companies_index: GAGAL TOTAL setelah retry ({exc!r}) — scan "
                f"berhenti prematur, {len(all_ids)} company ID yang sempat terkumpul "
                f"TETAP dipakai (partial). Cursor di-reset (run berikutnya mulai dari awal)."
            )
            resume_cursor = None
            break

        items       = data.get("items", [])
        next_cursor = data.get("nextCursor")

        for i in items:
            if i not in seen_ids:
                seen_ids.add(i)
                all_ids.append(i)

        if not next_cursor or not items:
            # siklus penuh selesai — reset cursor biar run berikutnya mulai dari awal
            resume_cursor = None
            break
        cursor = next_cursor
    else:
        # loop selesai tanpa break -> kena safety cap, simpan cursor terakhir untuk resume
        resume_cursor = cursor
        log.info(
            f"fetch_all_companies_index: MENTOK di safety cap {COMPANY_SCAN_MAX_PAGES} "
            f"halaman — {len(all_ids)} company ID terkumpul. Cursor disimpan, "
            f"run berikutnya resume (incremental)."
        )

    log.info(
        f"fetch_all_companies_index: {len(all_ids)} company ID terkumpul, fetching "
        f"detail per-grup ({COMPANY_FLUSH_GROUP_SIZE}/grup, flush tiap grup selesai)..."
    )

    total_flushed = 0
    for g in range(0, len(all_ids), COMPANY_FLUSH_GROUP_SIZE):
        group_ids = all_ids[g:g + COMPANY_FLUSH_GROUP_SIZE]
        details = await _fetch_companies_detail_group(session, group_ids)
        rows = [_company_row_from_detail(cid, d) for cid, d in details.items()]
        if rows and flush_callback is not None:
            await flush_callback(rows)
        total_flushed += len(rows)
        log.info(
            f"fetch_all_companies_index: grup {g}-{g + len(group_ids)} selesai, "
            f"{len(rows)}/{len(group_ids)} detail berhasil & SUDAH DI-FLUSH ke DB "
            f"(total sejauh ini: {total_flushed}/{len(all_ids)})."
        )

    log.info(
        f"fetch_all_companies_index: SELESAI. {total_flushed}/{len(all_ids)} "
        f"company berhasil di-fetch & di-flush. resume_cursor="
        f"{resume_cursor[:16] + '...' if resume_cursor else None}"
    )
    return total_flushed, resume_cursor


async def verify_and_cleanup_stale_companies(
    session: aiohttp.ClientSession, stale_ids: list[str]
) -> tuple[int, int]:
    """Ganti logic lama "gak ke-touch scan >30 hari = dianggap dibongkar,
    hapus" — itu false positive rawan, urutan company.getCompanies reshuffle
    tiap request, jadi company yang masih hidup bisa kebetulan gak kejaring
    pagination berminggu-minggu.

    Fungsi ini verifikasi langsung tiap company_id kandidat stale via
    company.getById (token PAGINATE) — yang API-nya masih balas data
    direfresh (dianggap cuma keluput pagination), yang beneran gak ketemu
    baru dihapus (dianggap udah dibongkar/dijual).

    Storage app_db (spy_cache_store), dipindah dari Supabase. Signature
    berubah dari versi lama (param supabase dihapus).

    Return: (jumlah_direfresh, jumlah_dihapus_confirmed)."""
    from services.spy import cache_store as spy_store

    if not stale_ids:
        return 0, 0

    confirmed_alive, failed_chunks = await _run_detail_chunks(
        session,
        [stale_ids[i:i + COMPANY_BATCH_SIZE] for i in range(0, len(stale_ids), COMPANY_BATCH_SIZE)],
        _paginate_auth_headers(),
        _paginate_limiter,
        "STALE-VERIFY",
    )
    ids_in_failed_chunks = {cid for chunk in failed_chunks for cid in chunk}
    confirmed_dead = [
        cid for cid in stale_ids
        if cid not in confirmed_alive and cid not in ids_in_failed_chunks
    ]

    refreshed_count = 0
    if confirmed_alive:
        rows = [_company_row_from_detail(cid, d) for cid, d in confirmed_alive.items()]
        refreshed_count = await asyncio.to_thread(spy_store.upsert_companies_batch, rows)

    deleted_count = 0
    if confirmed_dead:
        deleted_count = await asyncio.to_thread(spy_store.delete_companies_batch, confirmed_dead)

    log.info(
        f"verify_and_cleanup_stale_companies: {len(stale_ids)} kandidat stale — "
        f"{refreshed_count} ternyata masih hidup (direfresh), {deleted_count} "
        f"confirmed dibongkar (dihapus), {len(ids_in_failed_chunks)} gagal "
        f"diverifikasi (dibiarkan, dicoba lagi cycle berikutnya)."
    )
    return refreshed_count, deleted_count
