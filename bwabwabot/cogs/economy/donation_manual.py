"""
cogs/economy/donation_manual.py  —  Pencatatan donasi manual (staff)

  xdonasitambah <country> <user> <jumlah> [DD/MM/YYYY]  — Tambah donasi manual
  xdonasihapus <id>                                     — Hapus entri donasi manual
  xdonasilist <country> [range]                         — Lihat entri donasi manual
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

import market as mkt

from services.economy.formatters import _fmt_money
from .base import EconomyBase, _embed, DONATION_RANGE_WEEKS


class DonationManualCommands(EconomyBase):

    @commands.command(name="donasitambah", aliases=["dontambah", "adddon"])
    @commands.has_permissions(manage_guild=True)
    async def cmd_donasi_tambah(
        self,
        ctx: commands.Context,
        country: str,
        username: str,
        amount: float,
        tanggal: Optional[str] = None,
    ) -> None:
        """xdonasitambah <negara> <username> <jumlah> [DD/MM/YYYY]
        Tambah donasi yang tidak terdeteksi otomatis oleh API WarEra."""
        if amount <= 0:
            await ctx.send("⚠️ Donation amount must be greater than 0.")
            return
        if self._session is None:
            await ctx.send("❌ Session not ready.")
            return

        if tanggal:
            try:
                parsed = datetime.strptime(tanggal, "%d/%m/%Y")
            except ValueError:
                await ctx.send("⚠️ Date format must be `DD/MM/YYYY`, e.g. `13/07/2026`.")
                return
            donation_date = parsed.strftime("%Y-%m-%d")
        else:
            donation_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async with ctx.typing():
            resolved = await mkt.fetch_country_id_by_name(
                self._session, country, headers=mkt.donation_headers(), with_cache=True
            )
            if resolved is None:
                await ctx.send(f"⚠️ Country `{country}` not found.")
                return
            country_id, country_name = resolved
            row = await self._db_add_manual_donation(
                country_id, username, amount, donation_date, str(ctx.author)
            )

        if row is None:
            await ctx.send(
                "❌ Failed to save manual entry. Make sure the `manual_donations` table "
                "exists in Supabase (see setup notes)."
            )
            return

        e = _embed(f"✅ Manual Donation Added — {country_name}", discord.Color.green())
        e.description = (
            f"**ID:** `{row.get('id')}`\n"
            f"**Name:** {username}\n"
            f"**Amount:** `{_fmt_money(amount)}` g\n"
            f"**Date:** {donation_date} (UTC)\n"
            f"**Added by:** {ctx.author.mention}"
        )
        await ctx.send(embed=e)

    @commands.command(name="donasihapus", aliases=["donhapus", "deldon"])
    @commands.has_permissions(manage_guild=True)
    async def cmd_donasi_hapus(self, ctx: commands.Context, entry_id: int) -> None:
        """xdonasihapus <id> — hapus entri donasi manual (id dari xdonasilist)."""
        ok = await self._db_delete_manual_donation(entry_id)
        if ok:
            await ctx.send(f"🗑️ Manual entry `{entry_id}` successfully deleted.")
        else:
            await ctx.send(f"⚠️ Entry `{entry_id}` not found or failed to delete.")

    @commands.command(name="donasilist", aliases=["donlist"])
    async def cmd_donasi_list(self, ctx: commands.Context, country: str, range_str: str = "1w") -> None:
        """xdonasilist <negara> [range] — lihat entri donasi manual beserta ID-nya."""
        weeks = DONATION_RANGE_WEEKS.get(range_str.strip().lower())
        if weeks is None:
            await ctx.send("⚠️ Range must be one of: `1w`, `2w`, `3w`, `4w`, `5w`.")
            return
        if self._session is None:
            await ctx.send("❌ Session not ready.")
            return

        async with ctx.typing():
            resolved = await mkt.fetch_country_id_by_name(
                self._session, country, headers=mkt.donation_headers(), with_cache=True
            )
            if resolved is None:
                await ctx.send(f"⚠️ Country `{country}` not found.")
                return
            country_id, country_name = resolved
            week_start = mkt.get_week_range_start(weeks)
            since_date = week_start.strftime("%Y-%m-%d")
            rows       = await self._db_get_manual_donations(country_id, since_date)

        if not rows:
            await ctx.send(f"No manual donation entries for **{country_name}** in this range.")
            return

        lines = [
            f"`#{row.get('id')}` — **{row.get('username')}** "
            f"`{_fmt_money(float(row.get('amount', 0) or 0))}`g "
            f"({row.get('donation_date')}) — added by {row.get('added_by')}"
            for row in rows
        ]
        e = _embed(f"📝 Manual Donations — {country_name}", discord.Color.blue())
        e.description = "\n".join(lines[:25])
        if len(lines) > 25:
            e.set_footer(text=f"Showing 25 of {len(lines)} entries.")
        await ctx.send(embed=e)
