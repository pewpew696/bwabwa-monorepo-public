"""cogs/spy/api/player_activity.py — refresh aktivitas pemilik company (21 Sept 2026).

Loop latar belakang yang mengisi/menyegarkan tabel player_activity (user_id,
last_connection_at) lewat batch user.getUserLite di token HUB. Dipakai nanti buat
menyaring hitungan company 'aktif' di xspy country & dashboard. Dibuat sebagai
kelas mandiri (bukan mixin) supaya tidak menyentuh MRO SpyCog."""

from __future__ import annotations

import asyncio
import logging
import time

from discord.ext import tasks

from ..constants import (
    PLAYER_ACTIVITY_BATCH_OWNERS,
    PLAYER_ACTIVITY_BOOT_DELAY_S,
    PLAYER_ACTIVITY_INTERVAL_MIN,
)

log = logging.getLogger("WarEraBot.spy")


class PlayerActivityRunner:
    def __init__(self, bot) -> None:
        self.bot = bot

    def start(self) -> None:
        if not self.refresh.is_running():
            self.refresh.start()
            log.info(
                f"[PLAYER ACTIVITY] loop dimulai (tiap {PLAYER_ACTIVITY_INTERVAL_MIN} mnt, "
                f"maks {PLAYER_ACTIVITY_BATCH_OWNERS} pemilik/putaran, tunda {PLAYER_ACTIVITY_BOOT_DELAY_S}s)"
            )

    def stop(self) -> None:
        self.refresh.cancel()

    @tasks.loop(minutes=PLAYER_ACTIVITY_INTERVAL_MIN)
    async def refresh(self) -> None:
        import market as mkt
        from services.spy import cache_store as spy_store

        session = getattr(self.bot, "_session", None)
        if session is None:
            return
        started = time.perf_counter()
        try:
            owners = await asyncio.to_thread(spy_store.get_owners_to_refresh, PLAYER_ACTIVITY_BATCH_OWNERS)
            if not owners:
                return
            result = await mkt.fetch_player_last_connections(session, owners)
            rows = list(result.items())
            saved = await asyncio.to_thread(spy_store.upsert_player_activity, rows)
            log.info(
                f"[PLAYER ACTIVITY] {len(owners)} pemilik antre, {len(result)} terjawab, "
                f"{saved} tersimpan dalam {time.perf_counter() - started:.0f}s"
            )
        except Exception as exc:
            log.error(f"refresh_player_activity: {exc!r}", exc_info=True)

    @refresh.before_loop
    async def _before_refresh(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(PLAYER_ACTIVITY_BOOT_DELAY_S)
