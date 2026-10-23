"""
cogs/economy/donation.py  —  xdonation <country> [range]
Donor leaderboard (ranking mingguan + tabel harian).
"""

from __future__ import annotations

import logging
import asyncio

from discord.ext import commands

import market as mkt
from services import visuals as vis

from .base import EconomyBase, DONATION_RANGE_WEEKS, DON_PER_COL_CAP, DON_MAX_COLS, DON_PAGE_CAP
from .embeds import build_donation_weekly_specs, build_donation_daily_specs
from .views import DonationPaginationView

log = logging.getLogger("WarEraBot.economy")


class DonationCommands(EconomyBase):

    @commands.command(name="donation", aliases=["don", "donate"])
    async def cmd_donation(self, ctx: commands.Context, country: str, range_str: str = "1w") -> None:
        weeks = DONATION_RANGE_WEEKS.get(range_str.strip().lower())
        if weeks is None:
            await ctx.send("⚠️ Range must be one of: `1w`, `2w`, `3w`, `4w`, `5w`.")
            return
        if not self._price_cache:
            await ctx.send("⏳ Data not ready yet.")
            return
        if self._session is None:
            await ctx.send("❌ Session not ready.")
            return

        async with ctx.typing():
            don_headers = mkt.donation_headers()
            resolved = await mkt.fetch_country_id_by_name(
                self._session, country, headers=don_headers, with_cache=True
            )
            if resolved is None:
                await ctx.send(f"⚠️ Country `{country}` not found.")
                return
            country_id, country_name = resolved

# sync cache: tarik transaksi BARU sejak scan terakhir (backfill penuh
            # kalau belum pernah discan) — data yang sudah ada tidak ditarik ulang
            new_count, sync_complete = await mkt.sync_donations_incremental(
                self._session, country_id
            )
            log.info(
                f"cmd_donation({country_name}): sync +{new_count} transaksi baru, "
                f"complete={sync_complete}"
            )

            week_start = mkt.get_week_range_start(weeks)
            since_iso  = week_start.isoformat().replace("+00:00", "Z")
            items      = await mkt.get_cached_donations(country_id, since_iso)
            complete   = sync_complete

            # ranking mingguan (dari cache)
            ranked, _ = mkt.aggregate_donations(items)

            # breakdown harian (dari cache)
            daily_map_raw = mkt.group_donations_by_day(items, top_n=15)

# resolve SEMUA buyerId unik sekaligus (bukan per baris) — cache-first
            # dengan TTL, sisanya fetch API dibatasi konkurensi biar gak 429 storm
            all_buyer_ids: set[str] = {buyer_id for buyer_id, _ in ranked}
            for ranked_day in daily_map_raw.values():
                all_buyer_ids.update(buyer_id for buyer_id, _ in ranked_day)
            username_map = await mkt.resolve_usernames_bulk(
                self._session, list(all_buyer_ids), headers=don_headers
            )

            weekly_totals: dict[str, float] = {}
            for buyer_id, total in ranked:
                uname = username_map.get(buyer_id, buyer_id[:8] + "...")
                weekly_totals[uname] = weekly_totals.get(uname, 0.0) + total

            daily_map: dict[str, list[tuple[str, float]]] = {}
            for day, ranked_day in daily_map_raw.items():
                resolved_day: list[tuple[str, float]] = []
                for buyer_id, total in ranked_day:
                    uname = username_map.get(buyer_id, buyer_id[:8] + "...")
                    resolved_day.append((uname, total))
                daily_map[day] = resolved_day

            # selipkan data manual (pelengkap donasi yang tidak terdeteksi API)
            since_date  = week_start.strftime("%Y-%m-%d")
            manual_rows = await self._db_get_manual_donations(country_id, since_date)

            for row in manual_rows:
                uname  = row.get("username") or "?"
                amount = float(row.get("amount", 0) or 0)
                day    = row.get("donation_date", "")
                weekly_totals[uname] = weekly_totals.get(uname, 0.0) + amount
                if day:
                    bucket = daily_map.setdefault(day, [])
                    bucket.append((uname, amount))
                    bucket.sort(key=lambda kv: kv[1], reverse=True)
                    daily_map[day] = bucket[:15]

        grand_total      = sum(weekly_totals.values())
        donor_rows       = sorted(weekly_totals.items(), key=lambda kv: kv[1], reverse=True)
        sorted_days_desc = sorted(daily_map.keys(), reverse=True)

        range_label = f"{week_start.strftime('%d %b %Y')} — now ({weeks}w, UTC)"
        incomplete_note = (
            "⚠️ Cache isn't fully synced yet — please try this command again in a moment.\n"
            if not complete else ""
        )
        manual_note = (
            f"📝 Includes {len(manual_rows)} manual entries\n"
            if manual_rows else ""
        )
        pre_notes = incomplete_note + manual_note

        weekly_specs = build_donation_weekly_specs(
            range_label, donor_rows, grand_total, DON_PER_COL_CAP, DON_MAX_COLS, DON_PAGE_CAP
        )
        daily_specs  = build_donation_daily_specs(sorted_days_desc, daily_map, DON_MAX_COLS)
        page_specs   = weekly_specs + daily_specs

        first_file = await asyncio.to_thread(vis.generate_donation_image, country_name=country_name, **page_specs[0])
        if first_file is None:
            await ctx.send("❌ Failed to generate donation tracker image.")
            return

        if len(page_specs) == 1:
            await ctx.send(content=pre_notes or None, file=first_file)
            return

        msg = await ctx.send(content=pre_notes or None, file=first_file)
        view         = DonationPaginationView(country_name, page_specs)
        view.message = msg
        await msg.edit(view=view)
