"""
cogs/spy/wage.py — `xspy wage` (admin-only, on-demand, mengikuti pola
WorkersMixin di workers.py).

Input: tidak ada / opsional tanggal (default: hari ini, UTC). Output: gaji
kotor tertinggi hari itu (pemilik pabrik + worker penerima, plus semua
pasangan owner+worker lain yang tie di nilai sama), gaji bersih tertinggi
(format sama), lalu rata-rata gaji kotor & bersih global hari itu.
"""

from __future__ import annotations

import asyncio
from services.spy.api_client import get_user_lite
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from .api import _bot_admin_check
from core.utils import make_embed

log = logging.getLogger("WarEraBot.spy")


class WageMixin:
    """Mixin — expects ApiMixin di final class (self._get_user_lite)."""

    async def _resolve_username(self, user_id: str | None) -> str:
        if not user_id:
            return "?"
        ud = await get_user_lite(self._session, user_id)
        if not ud:
            return f"`{user_id}`"
        return ud.get("username", f"`{user_id}`")

    async def _format_top_lines(self, entries: list[dict]) -> list[str]:
        if not entries:
            return ["-"]

        from services.spy import cache_store as spy_store

        company_ids = list({e["company_id"] for e in entries if e.get("company_id")})
        owner_map = spy_store.get_companies_owners_batch(company_ids)

        unique_user_ids = list({
            uid for e in entries
            for uid in (owner_map.get(e.get("company_id")), e.get("seller_id"))
            if uid
        })
        names = await asyncio.gather(*[self._resolve_username(uid) for uid in unique_user_ids])
        name_map = dict(zip(unique_user_ids, names))

        lines = []
        for e in entries:
            owner_id = owner_map.get(e.get("company_id"))
            owner_name = name_map.get(owner_id, "?") if owner_id else "?"
            worker_name = name_map.get(e.get("seller_id"), "?")
            lines.append(f"**{owner_name}** — `{e['value']:.3f}` → **{worker_name}**")
        return lines

    @commands.command(name="wage")
    @commands.check(_bot_admin_check)
    async def spy_wage(self, ctx: commands.Context) -> None:
        """Admin-only: gaji kotor & bersih tertinggi (per-PP) + rata-rata global hari ini.
        Example: xspy wage"""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async with ctx.typing():
            from services.territory import tax_store as store
            summary = await self.bot.loop.run_in_executor(
                None, store.get_daily_wage_summary, date_str
            )

            if not summary:
                await ctx.send(f"ℹ️ No wage data for date `{date_str}` yet.")
                return

            top_gross_lines = await self._format_top_lines(summary["top_gross"])
            top_net_lines = await self._format_top_lines(summary["top_net"])

        e = make_embed(f"💵 Wage — {date_str}", discord.Color.gold())
        e.add_field(name="🏆 Highest Gross Wage", value="\n".join(top_gross_lines), inline=False)
        e.add_field(name="💰 Highest Net Wage", value="\n".join(top_net_lines), inline=False)

        avg_gross = summary.get("avg_gross_wage")
        avg_net = summary.get("avg_net_wage")
        e.add_field(
            name="📈 Global Average",
            value=(
                f"Gross: `{avg_gross:.3f}`\n" if avg_gross is not None else "Gross: -\n"
            ) + (
                f"Net: `{avg_net:.3f}`" if avg_net is not None else "Net: -"
            ),
            inline=False,
        )
        e.set_footer(text=f"{summary['event_count']} enriched wage transactions today")

        await ctx.send(embed=e)

    @spy_wage.error
    async def spy_wage_error(self, ctx: commands.Context, error: Exception) -> None:
        from core.utils import ChannelNotAllowed
        if isinstance(error, ChannelNotAllowed):
            return
        if isinstance(error, commands.CheckFailure):
            return
        log.error(f"spy_wage error: {error}", exc_info=True)
        await ctx.send("❌ An error occurred.")
