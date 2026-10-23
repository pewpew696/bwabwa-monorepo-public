"""
cogs/economy/top.py  —  xtop [range]  (Top Gainers & Losers)
"""

from __future__ import annotations

from datetime import datetime

import discord
from discord.ext import commands

import market as mkt

from services.economy.formatters import _fmt_price, _fmt_pct
from .base import EconomyBase, _embed, TOP_RANGES, ITEM_EMOJI


class TopCommands(EconomyBase):

    @commands.command(name="top", aliases=["t"])
    async def cmd_top(self, ctx: commands.Context, range_str: str = "1d") -> None:
        hours = TOP_RANGES.get(range_str.strip().lower())
        if hours is None:
            await ctx.send("⚠️ Range must be one of: `1d`, `7d`, `30d`.")
            return
        async with ctx.typing():
            result = await mkt.fetch_top_movers(hours=hours)
        gainers, losers = result["gainers"], result["losers"]
        if not gainers and not losers:
            await ctx.send("⚠️ Not enough price history data yet.")
            return

        medals = {0: "🥇", 1: "🥈", 2: "🥉"}

        def _rows(items: list, icon: str) -> str:
            return "\n".join(
                f"{medals.get(i, f'#{i+1:02d}')} {ITEM_EMOJI.get(m['item'], '•')} **{m['item']}**\n"
                f"   {icon} `{'+' if m['change'] >= 0 else ''}{_fmt_pct(m['change'])}%`  `{_fmt_price(m['price_old'])}` → `{_fmt_price(m['price_new'])}`"
                for i, m in enumerate(items)
            ) or "—"

        e = _embed(f"📈 Top Movers — {range_str}", discord.Color.gold())
        e.add_field(name="🟢 Top Gainers", value=_rows(gainers, "▲"), inline=False)
        e.add_field(name="🔴 Top Losers",  value=_rows(losers,  "▼"), inline=False)
        e.set_footer(text=f"Range: {range_str}  •  bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
        await ctx.send(embed=e)
