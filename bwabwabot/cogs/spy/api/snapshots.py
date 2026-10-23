"""cogs/spy/api/snapshots.py — xspy check v3: daily growth tracking
(dmg & wealth snapshot harian, task loop 00:05 UTC). Dipecah dari api.py
(dulu 1 file 1175 baris)."""

from __future__ import annotations
from services.db import pool as db_pool
from services.spy.api_client import get_user_lite

import asyncio
import logging
from datetime import datetime, timezone, time as dt_time

from discord.ext import tasks

log = logging.getLogger("WarEraBot.spy")


class SnapshotMixin:
    """Mixin — expects self.bot dari class
    final. _get_user_lite sekarang di services.spy.api_client."""

    async def _touch_tracked_player(
        self, user_id: str, username: str | None, added_by: str | None = None
    ) -> None:
        """Upsert ke spy_tracked_players. User_id baru -> insert (self-expanding,
        siapa pun yang di-`xspy check` otomatis masuk daftar tracking harian).
        User_id sudah ada & username berubah -> geser last_known_username lama
        ke previous_username (cuma nyimpan 1 nama sebelumnya, sesuai keputusan
        user — bukan riwayat berlapis)."""
        if not username:
            return
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("spy_tracked_players")
                    .select("last_known_username")
                    .eq("user_id", user_id)
                    .limit(1)
                    .execute()
                )
            )
            row = res[0] if res else None
        except Exception as exc:
            log.error(f"_touch_tracked_player select {user_id}: {exc}")
            return

        if row is None:
            try:
                await asyncio.to_thread(
                    lambda: db_pool.table("spy_tracked_players").insert({
                        "user_id": user_id,
                        "last_known_username": username,
                        "added_by": added_by,
                    }).execute()
                )
            except Exception as exc:
                log.error(f"_touch_tracked_player insert {user_id}: {exc}")
            return

        old_name = row.get("last_known_username")
        if old_name and old_name != username:
            try:
                await asyncio.to_thread(
                    lambda: db_pool.table("spy_tracked_players").update({
                        "last_known_username": username,
                        "previous_username": old_name,
                    }).eq("user_id", user_id).execute()
                )
            except Exception as exc:
                log.error(f"_touch_tracked_player update {user_id}: {exc}")

    @tasks.loop(time=dt_time(hour=0, minute=5, tzinfo=timezone.utc))  # 00:05 UTC = 07:05 WIB
    async def refresh_daily_snapshots(self) -> None:
        """Snapshot harian (weekly_damage, total_damage, wealth) buat semua
        player di spy_tracked_players. Jalan tiap hari 00:05 UTC (~07:05 WIB),
        sedikit setelah reset weekly damage WarEra (Senin 07:00 WIB), supaya
        angka weekly yang ke-capture representatif utk hari itu."""
        log.info("[SPY SNAPSHOT] Mulai snapshot harian tracked players...")
        try:
            res = await asyncio.to_thread(
                lambda: db_pool.table("spy_tracked_players").select("user_id").execute()
            )
            user_ids = [r["user_id"] for r in (res or [])]
        except Exception as exc:
            log.error(f"refresh_daily_snapshots fetch tracked_players: {exc}", exc_info=True)
            return

        today = datetime.now(timezone.utc).date().isoformat()
        ok, failed = 0, 0
        for uid in user_ids:
            data = await get_user_lite(self._session, uid)
            if not data:
                failed += 1
                continue
            rankings = data.get("rankings", {})
            username = data.get("username")
            try:
                await asyncio.to_thread(
                    lambda uid=uid, username=username, rankings=rankings: db_pool.table("spy_daily_snapshots").upsert({
                        "user_id": uid,
                        "snapshot_date": today,
                        "username": username,
                        "weekly_damage": float((rankings.get("weeklyUserDamages") or {}).get("value") or 0),
                        "total_damage": float((rankings.get("userDamages") or {}).get("value") or 0),
                        "wealth": float((rankings.get("userWealth") or {}).get("value") or 0),
                    }, on_conflict="user_id,snapshot_date").execute()
                )
                await self._touch_tracked_player(uid, username)
                ok += 1
            except Exception as exc:
                log.error(f"refresh_daily_snapshots upsert {uid}: {exc}")
                failed += 1
            await asyncio.sleep(0.3)  # ramah rate-limit API WarEra

        log.info(f"[SPY SNAPSHOT] Selesai. ok={ok} failed={failed} total={len(user_ids)}")

    @refresh_daily_snapshots.before_loop
    async def _before_daily_snapshots(self) -> None:
        await self.bot.wait_until_ready()
