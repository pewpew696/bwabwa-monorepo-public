"""
cogs/spy/check.py  —  `xspy check` (daily growth tracking: dmg & wealth) dan
`xspy scan` (progress background scan company_index, TIDAK diubung).

v3: xspy check cuma fokus deteksi kenaikan wealth yang nggak wajar
(rekonsiliasi ledger transaksi). Diganti TOTAL atas keputusan user jadi
fitur growth harian yang lebih sederhana: dmg & wealth hari ini vs snapshot
terakhir. Tracking self-expanding — siapa pun yang di-check otomatis masuk
daftar snapshot harian (ApiMixin.refresh_daily_snapshots).

CheckMixin butuh ApiMixin (search_user_ids, get_user_lite, touch_tracked_player,
_session). Command didefinisikan lepas, di-attach ke group `xspy` di __init__.py.
"""

from __future__ import annotations

import asyncio
from services.db import pool as db_pool
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from core.blocklist import is_player_blocked
from core.permissions import get_level, LEVEL_BOT_ADMIN
from core.messages import MSG_NO_PERM_ADMIN, MSG_BLOCKED_SPY

from .api import _bot_admin_check
from .constants import (
    ITEM_EMOJI,
    COMPANY_ESTIMATED_TOTAL,
    COMPANY_SCAN_INTERVAL_HOURS,
)
from core.utils import make_embed
from services.spy.utils import ago, not_found_msg
from services.spy.search import find_player_exact

log = logging.getLogger("WarEraBot.spy")


class CheckMixin:
    """Mixin — expects ApiMixin di final class."""

    @commands.command(name="check")
    async def spy_check(self, ctx: commands.Context, *, nama: str) -> None:
        """Daily growth check: weekly dmg (live), total dmg & wealth vs
        snapshot terakhir. Terbuka untuk siapa saja. Player yang di-check
        otomatis masuk daftar tracking harian (self-expanding) — lihat
        ApiMixin.refresh_daily_snapshots.
        Example: xspy check sagukeju | xspy check sagukeju 30 (banding N hari lalu)"""
        # Hari opsional di ujung: "nama 30" / "nama 30d". Angka cuma dianggap
        # hari kalau berdiri sendiri sebagai kata terakhir & masih ada nama di depannya.
        days_back = None
        _parts = nama.rsplit(None, 1)
        if len(_parts) == 2:
            _tok = _parts[1].lower()
            if _tok.endswith("d"):
                _tok = _tok[:-1]
            if _tok.isdigit():
                nama = _parts[0].strip()
                _n = int(_tok)
                days_back = min(_n, 36500) if _n > 0 else None
        async with ctx.typing():
            data, suggestions = await find_player_exact(self._session, nama)
            if not data:
                await ctx.send(f"⚠️ {not_found_msg('Player', nama, suggestions, md=True)}")
                return

        user_id = data["_id"]
        if await is_player_blocked(user_id):
            if await get_level(ctx.author) < LEVEL_BOT_ADMIN:
                await ctx.send(MSG_BLOCKED_SPY)
                return

        username = data.get("username", nama)
        rankings = data.get("rankings", {})
        weekly_damage = float((rankings.get("weeklyUserDamages") or {}).get("value") or 0)
        total_damage = float((rankings.get("userDamages") or {}).get("value") or 0)
        total_wealth = float((rankings.get("userWealth") or {}).get("value") or 0)
        last_worked = ago((data.get("dates") or {}).get("lastWorkAt"))

        # Ambil state tracking LAMA dulu (sebelum di-touch) buat nentuin nama
        # sebelumnya yang ditampilkan — konsisten dengan logic di
        # _touch_tracked_player (1 nama terakhir aja, bukan riwayat berlapis).
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("spy_tracked_players")
                    .select("last_known_username, previous_username")
                    .eq("user_id", user_id)
                    .limit(1)
                    .execute()
                )
            )
            tracked_row = res[0] if res else None
        except Exception as exc:
            log.error(f"spy_check fetch tracked_players: {exc}")
            tracked_row = None

        if tracked_row is None:
            previous_username = None
        elif tracked_row.get("last_known_username") and tracked_row["last_known_username"] != username:
            previous_username = tracked_row["last_known_username"]
        else:
            previous_username = tracked_row.get("previous_username")

        await self._touch_tracked_player(user_id, username, added_by=str(ctx.author.id))

        # Snapshot pembanding: yang terakhir SEBELUM hari ini (bukan cuma
        # "kemarin" persis, karena bisa ada gap kalau tracking baru mulai).
        today = datetime.now(timezone.utc).date()
        fell_back = False
        try:
            if days_back:
                # Mode N hari: snapshot terdekat PADA/SEBELUM (hari ini - N).
                target_date = today - timedelta(days=days_back)
                snap_res = await asyncio.to_thread(
                    lambda: (
                        db_pool.table("spy_daily_snapshots")
                        .select("snapshot_date, total_damage, wealth")
                        .eq("user_id", user_id)
                        .lte("snapshot_date", target_date.isoformat())
                        .order("snapshot_date", desc=True)
                        .limit(1)
                        .execute()
                    )
                )
                prev = snap_res[0] if snap_res else None
                if prev is None:
                    # Riwayat player lebih pendek dari N hari -> pakai snapshot
                    # TERLAMA yang ada (sebelum hari ini), tanggalnya ditampilkan.
                    snap_res = await asyncio.to_thread(
                        lambda: (
                            db_pool.table("spy_daily_snapshots")
                            .select("snapshot_date, total_damage, wealth")
                            .eq("user_id", user_id)
                            .lt("snapshot_date", today.isoformat())
                            .order("snapshot_date", desc=False)
                            .limit(1)
                            .execute()
                        )
                    )
                    prev = snap_res[0] if snap_res else None
                    fell_back = prev is not None
            else:
                snap_res = await asyncio.to_thread(
                    lambda: (
                        db_pool.table("spy_daily_snapshots")
                        .select("snapshot_date, total_damage, wealth")
                        .eq("user_id", user_id)
                        .lt("snapshot_date", today.isoformat())
                        .order("snapshot_date", desc=True)
                        .limit(1)
                        .execute()
                    )
                )
                prev = snap_res[0] if snap_res else None
        except Exception as exc:
            log.error(f"spy_check fetch snapshot: {exc}")
            prev = None

        # Upsert snapshot HARI INI dari data live ini juga (bukan cuma nunggu
        # scheduler jam 07:05), supaya `xspy check` berulang di hari yang sama
        # tetap konsisten & besok punya baseline yang fresh.
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("spy_daily_snapshots").upsert({
                    "user_id": user_id,
                    "snapshot_date": today.isoformat(),
                    "username": username,
                    "weekly_damage": weekly_damage,
                    "total_damage": total_damage,
                    "wealth": total_wealth,
                }, on_conflict="user_id,snapshot_date").execute()
            )
        except Exception as exc:
            log.error(f"spy_check upsert snapshot: {exc}")

        lines = [f"**Username:** {username}"]
        if previous_username:
            lines.append(f"**Previously:** {previous_username}")
        lines.append(f"**Weekly Dmg:** {weekly_damage:,.0f}")

        if prev:
            prev_date = datetime.fromisoformat(prev["snapshot_date"]).date()
            gap_days = (today - prev_date).days
            period = "since yesterday" if gap_days <= 1 else f"in the last {gap_days} days"
            if fell_back:
                period = f"since {prev_date.isoformat()} (oldest data, {gap_days}d)"
            dmg_delta = total_damage - float(prev.get("total_damage") or 0)
            wealth_delta = total_wealth - float(prev.get("wealth") or 0)
            lines.append(f"**Total Dmg:** {total_damage:,.0f} ({dmg_delta:+,.0f} {period})")
            lines.append(f"**Total Wealth:** {total_wealth:,.2f} G ({wealth_delta:+,.2f} {period})")
        else:
            lines.append(f"**Total Dmg:** {total_damage:,.0f}")
            lines.append(f"**Total Wealth:** {total_wealth:,.2f} G")
            lines.append("_(First check — no comparison data yet, run this again tomorrow)_")

        lines.append(f"**Last Worked:** {last_worked}")

        e = make_embed(f"🕵️ Spy Check: {username}", discord.Color.blurple())
        e.description = "\n".join(lines)
        await ctx.send(embed=e)

    @spy_check.error
    async def spy_check_error(self, ctx: commands.Context, error: Exception) -> None:
        log.error(f"spy_check error: {error}", exc_info=True)
        await ctx.send("❌ An error occurred.")

    # --- xspy scan — progress company_index dalam bahasa yang gampang dibaca ---

    @commands.command(name="scan")
    @commands.check(_bot_admin_check)
    async def spy_scan_status(self, ctx: commands.Context) -> None:
        """Tampilkan progress background scan company_index — TIDAK perlu buka
        app_db manual, tinggal jalankan command ini kapan aja."""
        from services.spy import cache_store as spy_store
        async with ctx.typing():
            now = datetime.now(timezone.utc)
            one_hour_ago = (now - timedelta(hours=1)).isoformat()
            one_day_ago  = (now - timedelta(hours=24)).isoformat()

            try:
                stats = await asyncio.to_thread(spy_store.get_company_index_stats, one_hour_ago, one_day_ago)
                total = stats["total"]
                last_updated = stats["last_updated"]
                last_hour_count = stats["last_hour_count"]
                last_day_count = stats["last_day_count"]
            except Exception as exc:
                log.error(f"spy_scan_status: {exc}", exc_info=True)
                await ctx.send("❌ Failed to fetch scan progress data.")
                return

        pct = min(100.0, (total / COMPANY_ESTIMATED_TOTAL) * 100) if COMPANY_ESTIMATED_TOTAL else 0.0
        bar_filled = int(pct // 5)
        bar = "🟩" * bar_filled + "⬜" * (20 - bar_filled)

        if last_updated:
            last_dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            minutes_ago = (now - last_dt).total_seconds() / 60
            expected_minutes = COMPANY_SCAN_INTERVAL_HOURS * 60
            if minutes_ago <= expected_minutes * 1.5:
                status = "🟢 Active — scan running normally"
            elif minutes_ago <= expected_minutes * 4:
                status = "🟡 Slow — might still be processing one big cycle, not necessarily stuck"
            else:
                jam = minutes_ago / 60
                status = f"🔴 Possibly stopped — no update at all for {jam:.1f}h"
            if minutes_ago < 1:
                last_text = "just now"
            elif minutes_ago < 60:
                last_text = f"{minutes_ago:.0f} min ago"
            else:
                last_text = f"{minutes_ago / 60:.1f}h ago"
        else:
            status = "⚪ Never scanned"
            last_text = "-"

        e = make_embed("📊 Progress Company Scan", discord.Color.blurple())
        e.description = (
            f"{bar}\n"
            f"**{total:,} / ~{COMPANY_ESTIMATED_TOTAL:,} company** (~{pct:.1f}%)"
        )
        e.add_field(name="Status", value=status, inline=False)
        e.add_field(name="Last Update", value=last_text, inline=True)
        e.add_field(name="Updated Last 1h", value=f"{last_hour_count:,} company", inline=True)
        e.add_field(name="Updated Last 24h", value=f"{last_day_count:,} company", inline=True)
        e.set_footer(text=(
            f"The ~{COMPANY_ESTIMATED_TOTAL:,} figure is an estimate (not exact from the API), "
            f"automatic scan runs every {COMPANY_SCAN_INTERVAL_HOURS}h."
        ))
        await ctx.send(embed=e)

    @spy_scan_status.error
    async def spy_scan_status_error(self, ctx: commands.Context, error: Exception) -> None:
        from core.utils import ChannelNotAllowed
        if isinstance(error, ChannelNotAllowed):
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send(MSG_NO_PERM_ADMIN)
        else:
            log.error(f"spy_scan_status error: {error}", exc_info=True)
            await ctx.send("❌ An error occurred.")