"""
cogs/economy/refresh.py  —  xrefresh  (Force refresh prices & bonuses)
"""

from __future__ import annotations

from datetime import datetime, timezone

from discord.ext import commands

import market as mkt
from services.market import snapshot as msnap

from .base import EconomyBase, _embed
import discord


class RefreshCommands(EconomyBase):

    @commands.command(name="refresh", aliases=["r"])
    async def cmd_refresh(self, ctx: commands.Context) -> None:
        async with ctx.typing():
            if self._session is None:
                await ctx.send("❌ Session not ready.")
                return
            snap      = await msnap.get_market_snapshot(self._session, force=True)
            prices    = snap["prices"] if snap else {}
            bonuses   = await mkt.fetch_max_bonuses(self._session, with_cache=True)
            breakdown = await mkt.fetch_bonus_breakdown(self._session, top_n=5, with_cache=True)
            if snap:
                await self.bot._apply_market_snapshot(snap)
            if bonuses:
                self._auto_bonus_cache.update(bonuses)
            if breakdown:
                self._bonus_breakdown.clear()
                self._bonus_breakdown.update(breakdown)
                self._bonus_deposit_ends.clear()
                self._bonus_deposit_ends.update(
                    await mkt.fetch_bonus_deposit_ends(self._session, breakdown, with_cache=True)
                )
        e = _embed("🔄 Refresh Complete", discord.Color.green())
        e.add_field(name="Prices",           value=f"`{len(prices)}` items",  inline=True)
        e.add_field(name="Production Bonus", value=f"`{len(bonuses)}` items", inline=True)
        await ctx.send(embed=e)
