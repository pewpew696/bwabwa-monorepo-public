"""cogs/spy/api/company_scan.py — background scan company index (task loop
tiap COMPANY_SCAN_INTERVAL_HOURS) + cleanup stale company (task loop harian).

Full-scan di sini cuma melayani fitur agregat region/negara (xspy country,
web API halaman negara, xspy scan) -- bukan lagi demi akurasi xspy player,
itu udah ditangani terpisah lewat market.fetch_and_cache_user_companies
(on-demand per user, lihat companies.py). Interval 12 jam karena freshness
data agregat jauh lebih longgar dibanding kebutuhan real-time dulu."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta, time as dt_time

from discord.ext import tasks

from ..constants import (
    COMPANY_SCAN_INTERVAL_HOURS,
    COMPANY_STALE_DAYS,
    COMPANY_FULL_STALE_DAYS,
    COMPANY_FULL_STALE_BATCH,
    COMPANY_PRIORITY_SCAN_INTERVAL_HOURS,
    COMPANY_PRIORITY_BATCH,
)

log = logging.getLogger("WarEraBot.spy")


class CompanyScanMixin:
    """Mixin — expects self.bot, self._session dari class
    final (SpyCog di __init__.py). `_session` didefinisikan di
    sini karena harus ada persis 1x di seluruh MRO ApiMixin — mixin lain
    (lookup, inventory, dst) memakainya lewat `self` di class final."""

    @property
    def _session(self):
        return self.bot._session

    # --- company index background scan (tiap 12 jam) ---

    @tasks.loop(hours=COMPANY_SCAN_INTERVAL_HOURS)
    async def refresh_company_index(self) -> None:
        """Scan inkremental company index (tiap COMPANY_SCAN_INTERVAL_HOURS).

        Cursor disimpan di tabel company_scan_state (row 'global'): kalau cap
        safety (COMPANY_SCAN_MAX_PAGES) kepentok, cursor terakhir dipakai run
        berikutnya biar company di luar ~150k pertama tetap ter-cover. Kalau
        siklus penuh selesai (nextCursor null), cursor di-reset dan run
        berikutnya mulai dari awal — cover company baru.

        Cleanup stale tidak dijalankan di sini (task terpisah).
        """
        import market as mkt
        from services.spy import cache_store as spy_store
        start_time = time.perf_counter()
        try:
            # --- tahap 1: refresh company prioritas (item_code/region_id berubah) ---
            # Diproses duluan SEBELUM scan cursor-based biasa supaya data yang
            # ketahuan berubah gak nunggu satu siklus penuh (12 jam) lagi.
            await self._refresh_priority_companies(mkt, spy_store)

            state = await asyncio.to_thread(spy_store.get_company_scan_state)
            start_cursor = state.get("last_cursor")
            cycle_count = int(state.get("cycle_count") or 0)
            if start_cursor:
                log.info(
                    f"[COMPANY SCAN] Resume dari cursor tersimpan "
                    f"({start_cursor[:16]}...) — cycle #{cycle_count}."
                )
            else:
                log.info(
                    f"[COMPANY SCAN] Mulai scan dari awal (cycle #{cycle_count + 1})."
                )
            total_flushed, resume_cursor = await mkt.fetch_all_companies_index(
                self._session,
                flush_callback=self._flush_company_batch,
                start_cursor=start_cursor,
            )
            # kalau resume_cursor None -> siklus penuh selesai, naikkan counter
            new_cycle = cycle_count if resume_cursor else cycle_count + 1
            await asyncio.to_thread(
                spy_store.set_company_scan_state, resume_cursor, new_cycle
            )
            elapsed = time.perf_counter() - start_time
            log.info(
                f"[COMPANY SCAN] Selesai dalam {elapsed/60:.1f} menit. "
                f"{total_flushed} company di-fetch & di-flush. "
                f"resume_cursor={'yes' if resume_cursor else 'no (siklus selesai)'}, "
                f"cycle_count={new_cycle}."
            )
        except Exception as exc:
            log.error(f"refresh_company_index: {exc}", exc_info=True)

    @refresh_company_index.before_loop
    async def _before_scan(self) -> None:
        await self.bot.wait_until_ready()

    async def _refresh_priority_companies(self, mkt, spy_store) -> None:
        """Tahap 1 refresh_company_index — refresh company yang item_code/
        region_id-nya ketahuan BERUBAH saat flush batch sebelumnya (dicatat
        di tabel company_scan_priority oleh upsert_companies_batch). Detail
        company ini di-fetch langsung (batch company.getById) lalu di-upsert;
        yang sukses dibersihin dari daftar prioritas biar gak diproses dobel.

        Catatan: kalau _fetch_companies_detail_group gagal total (semua chunk
        error), company gagal dibiarkan di daftar prioritas — di-cycle
        berikutnya dicoba lagi otomatis."""
        try:
            priority_ids = await asyncio.to_thread(
                spy_store.get_priority_company_ids, COMPANY_PRIORITY_BATCH
            )
        except Exception as exc:
            log.error(f"_refresh_priority_companies: gagal ambil daftar prioritas: {exc}", exc_info=True)
            return

        if not priority_ids:
            return

        log.info(
            f"[COMPANY SCAN] {len(priority_ids)} company prioritas "
            f"(item_code/region_id berubah) — fetch detail duluan sebelum scan utama..."
        )
        try:
            details = await mkt._fetch_companies_detail_group(self._session, priority_ids)
        except Exception as exc:
            log.error(f"_refresh_priority_companies: fetch detail gagal total: {exc}", exc_info=True)
            return

        rows = [mkt._company_row_from_detail(cid, d) for cid, d in details.items()]
        refreshed = 0
        if rows:
            refreshed = await asyncio.to_thread(spy_store.upsert_companies_batch, rows)

        # Bersihin yang beneran ke-fetch & ke-upsert; yang gagal divetch
        # (chunk error) biar kecoba lagi cycle berikutnya.
        done_ids = [cid for cid, d in details.items()]
        cleared = await asyncio.to_thread(spy_store.clear_priority_company_ids, done_ids)
        log.info(
            f"[COMPANY SCAN] Prioritas selesai — kandidat={len(priority_ids)} "
            f"detail_diterima={len(details)} diupsert={refreshed} dibersihkan={cleared}."
        )

    async def _flush_company_batch(self, rows: list[dict]) -> None:
        """Callback yang dipanggil market.fetch_all_companies_index tiap grup
        (~COMPANY_FLUSH_GROUP_SIZE company) selesai di-fetch — upsert langsung
        ke app_db (spy_cache_store), bukan nunggu seluruh ~100k company
        kelar. Ini bikin progress kesimpen real-time dan kalau proses mati di
        tengah, hasil yang udah sukses tetap aman di tabel."""
        from services.spy import cache_store as spy_store
        upserted = await asyncio.to_thread(spy_store.upsert_companies_batch, rows)
        log.info(f"_flush_company_batch: {upserted}/{len(rows)} row ter-upsert.")

    # --- cleanup stale terpisah (1x sehari) ---

    @tasks.loop(time=dt_time(hour=3, minute=0, tzinfo=timezone.utc))
    async def cleanup_stale_task(self) -> None:
        """Bersihkan data company stale 1x sehari (jam 3 pagi UTC).
        Tidak mengganggu jadwal scan utama karena berjalan terpisah.
        """
        log.info("[CLEANUP TASK] Mulai verifikasi & cleanup company stale (jadwal harian)...")
        await self._cleanup_stale_companies()

    @cleanup_stale_task.before_loop
    async def _before_cleanup(self) -> None:
        await self.bot.wait_until_ready()

    async def _cleanup_stale_companies(self) -> None:
        """Verifikasi company yang sudah lama tidak ke-scan (>COMPANY_STALE_DAYS).
        Dipanggil oleh cleanup_stale_task (1x/hari) — bukan dari scan utama.
        Storage: app_db (spy_cache_store), dipindah dari Supabase.

        Perubahan: ditambahkan limit 500 kandidat per jalan agar tidak
        memproses terlalu banyak sekaligus, sehingga durasi tetap terkendali.
        """
        import market as mkt
        from services.spy import cache_store as spy_store
        try:
            stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=COMPANY_STALE_DAYS)).isoformat()
            stale_ids = await asyncio.to_thread(spy_store.get_stale_company_ids, stale_cutoff, 500)
        except Exception as exc:
            log.error(f"_cleanup_stale_companies: gagal ambil kandidat stale: {exc}", exc_info=True)
            return

        if not stale_ids:
            log.info(f"[CLEANUP] Tidak ada kandidat stale (>{COMPANY_STALE_DAYS}d) untuk diproses.")
            return

        log.info(
            f"[CLEANUP] {len(stale_ids)} kandidat stale (>{COMPANY_STALE_DAYS}d) "
            f"— memverifikasi langsung ke API sebelum hapus..."
        )
        refreshed, deleted = await mkt.verify_and_cleanup_stale_companies(self._session, stale_ids)

        try:
            actual_count = await asyncio.to_thread(spy_store.get_company_count)
        except Exception as exc:
            log.error(f"_cleanup_stale_companies verify count gagal: {exc}", exc_info=True)
            actual_count = -1

        log.info(
            f"[CLEANUP] Selesai — kandidat={len(stale_ids)} "
            f"masih_hidup_direfresh={refreshed} confirmed_dihapus={deleted} "
            f"total_rows_di_tabel={actual_count}"
        )

    # --- deteksi company mati lebih cepat (is_full stale, tiap 6 jam) ---

    @tasks.loop(hours=COMPANY_PRIORITY_SCAN_INTERVAL_HOURS)
    async def full_stale_check_task(self) -> None:
        """Verifikasi kandidat company mati lebih cepat (tiap 6 jam): company
        is_full=True yang updated_at-nya lebih tua dari COMPANY_FULL_STALE_DAYS
        dipastikan langsung ke API (company.getById batch) — yang confirmed
        hilang dihapus, yang masih ada di-refresh (updated_at naik, jadi gak
        kejaring lagi putaran berikutnya)."""
        import market as mkt
        from services.spy import cache_store as spy_store
        start_time = time.perf_counter()
        try:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=COMPANY_FULL_STALE_DAYS)
            ).isoformat()
            candidates = await asyncio.to_thread(
                spy_store.get_full_stale_company_ids, cutoff, COMPANY_FULL_STALE_BATCH
            )
        except Exception as exc:
            log.error(f"full_stale_check_task: gagal ambil kandidat is_full-stale: {exc}", exc_info=True)
            return

        if not candidates:
            log.info(
                f"[FULL-STALE CHECK] Tidak ada kandidat (is_full=True, "
                f">{COMPANY_FULL_STALE_DAYS}d) putaran ini."
            )
            return

        log.info(
            f"[FULL-STALE CHECK] {len(candidates)} kandidat is_full-stale "
            f"(>{COMPANY_FULL_STALE_DAYS}d) — verifikasi ke API sebelum hapus..."
        )
        refreshed, deleted = await mkt.verify_and_cleanup_stale_companies(self._session, candidates)
        elapsed = time.perf_counter() - start_time
        log.info(
            f"[FULL-STALE CHECK] Selesai dalam {elapsed:.1f}s — kandidat={len(candidates)} "
            f"masih_hidup_direfresh={refreshed} confirmed_dihapus={deleted}."
        )

    @full_stale_check_task.before_loop
    async def _before_full_stale(self) -> None:
        await self.bot.wait_until_ready()
