"""
cogs/economy/profit.py  —  xprofit [AE]  (Daily profit ranking)
"""

from __future__ import annotations

import discord
from discord.ext import commands

from services.economy.formatters import _fmt_price, _fmt_pct, _fmt_money
from .base import EconomyBase, _embed, AE_PP_PER_DAY, PRODUCTION_CHAIN, ITEM_EMOJI


class ProfitCommands(EconomyBase):

    @commands.command(name="profit", aliases=["p"])
    async def cmd_profit(self, ctx: commands.Context, ae: int = 6) -> None:
        if not self._price_cache:
            await ctx.send("⏳ Data not ready yet.")
            return
        if ae not in AE_PP_PER_DAY:
            await ctx.send("⚠️ AE must be between 1-7.")
            return

        base_pp = AE_PP_PER_DAY[ae]
        rows    = []
        for name, chain in PRODUCTION_CHAIN.items():
            sell_price = self._price_cache.get(name)
            if sell_price is None:
                continue
            bonus_pct, source = self._get_bonus(name)
            pp_per_day    = base_pp * (1 + bonus_pct / 100)
            units_per_day = pp_per_day / chain["pp"]
            revenue       = units_per_day * sell_price
            cost          = 0.0
            if chain["input"] is not None:
                input_name, input_qty = chain["input"]
                cost = units_per_day * input_qty * self._price_cache.get(input_name, 0)
            rows.append((
                revenue - cost, name, units_per_day, sell_price,
                bonus_pct, "🔧" if source == "manual" else "🌐",
                ITEM_EMOJI.get(name, "•"),
            ))
        rows.sort(key=lambda r: r[0], reverse=True)

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        chunk, parts = "", []
        for rank, (profit, name, units, price, bonus_pct, tag, emoji) in enumerate(rows, 1):
            row = (
                f"{medals.get(rank, f'#{rank:02d}')} {emoji} **{name}** {tag} (+{_fmt_pct(bonus_pct)}%)\n"
                f"   💰 Profit/day: **+{_fmt_money(profit)}** | Output: {units:,.1f} | Price: {_fmt_price(price)}\n"
            )
            if len(chunk) + len(row) > 950:
                parts.append(chunk); chunk = ""
            chunk += row
        if chunk:
            parts.append(chunk)

        for i, part in enumerate(parts):
            e = _embed(f"📊 Daily Profit — AE{ae} ({base_pp:,} PP/day)", discord.Color.gold())
            e.description = part
            if i == 0:
                e.set_footer(text="🌐 = auto production bonus   🔧 = manual override")
            await ctx.send(embed=e)
