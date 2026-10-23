"""cogs/spy/api/company_owner_refresh.py — refresh company per-owner (22 Sept 2026).

Pengganti scan company lama (company_scan.py, full-scan 150k company/siklus,
selalu mentok). Loop ini cuma proses pemilik yang login dalam jendela waktu
terakhir (lewat tabel player_activity), lalu panggil
market.refresh_owner_companies per pemilik — paginate company.getCompanies,
hapus company yang sudah tidak muncul (dibongkar), upsert detail ke
company_index, dan sinkron worker ke company_workers. Pakai token DONATION
(paling jarang dipakai, tidak bersinggungan dengan company_scan/tax collector).

Dibuat sebagai kelas mandiri (bukan mixin), pola sama seperti
PlayerActivityRunner di player_activity.py — supaya tidak menyentuh MRO SpyCog."""

from __future__ import annotations

import asyncio
import logging
import time

from discord.ext import tasks

from ..constants import (
    COMPANY_OWNER_REFRESH_BATCH_OWNERS,
    COMPANY_OWNER_REFRESH_BOOT_DELAY_S,
    COMPANY_OWNER_REFRESH_INTERVAL_MIN,
    COMPANY_OWNER_REFRESH_LOOKBACK_MIN,
)

log = logging.getLogger("WarEraBot.spy")


class CompanyOwnerRefreshRunner:
    def __init__(self, bot) -> None:
        self.bot = bot

    def start(self) -> None:
        if not self.refresh.is_running():
            self.refresh.start()
        log.info(
            f"[COMPANY OWNER REFRESH] loop dimulai (tiap {COMPANY_OWNER_REFRESH_INTERVAL_MIN} mnt, "
            f"lookback {COMPANY_OWNER_REFRESH_LOOKBACK_MIN} mnt, "
            f"maks {COMPANY_OWNER_REFRESH_BATCH_OWNERS} pemilik/putaran, "
            f"tunda {COMPANY_OWNER_REFRESH_BOOT_DELAY_S}s)"
        )

    def stop(self) -> None:
        self.refresh.cancel()

    @tasks.loop(minutes=COMPANY_OWNER_REFRESH_INTERVAL_MIN)
    async def refresh(self) -> None:
        import market as mkt
        from services.spy import cache_store as spy_store

        session = getattr(self.bot, "_session", None)
        if session is None:
            return

        started = time.perf_counter()
        try:
            owners = await asyncio.to_thread(
                spy_store.get_recently_logged_in_owners,
                COMPANY_OWNER_REFRESH_LOOKBACK_MIN,
                COMPANY_OWNER_REFRESH_BATCH_OWNERS,
            )
            if not owners:
                log.info("[COMPANY OWNER REFRESH] Tidak ada pemilik login baru di jendela ini.")
                return

            total_fetched = 0
            total_deleted = 0
            total_workers = 0
            failed = 0

            for owner_id in owners:
                try:
                    result = await mkt.refresh_owner_companies(session, owner_id)
                    total_fetched += result["fetched"]
                    total_deleted += result["deleted"]
                    total_workers += result["workers_synced"]
                except Exception as exc:
                    failed += 1
                    log.error(f"[COMPANY OWNER REFRESH] gagal utk owner {owner_id}: {exc!r}")

            log.info(
                f"[COMPANY OWNER REFRESH] {len(owners)} pemilik diproses ({failed} gagal), "
                f"{total_fetched} company di-refresh, {total_deleted} dihapus, "
                f"{total_workers} baris worker disinkron, dalam {time.perf_counter() - started:.0f}s"
            )
        except Exception as exc:
            log.error(f"company_owner_refresh: {exc!r}", exc_info=True)

    @refresh.before_loop
    async def _before_refresh(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(COMPANY_OWNER_REFRESH_BOOT_DELAY_S)
