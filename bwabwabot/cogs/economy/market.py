"""
cogs/economy/market.py  —  xmarket  (Spread & Volume 24h, 2 halaman)
"""

from __future__ import annotations

from discord.ext import commands

import market as mkt

from .base import EconomyBase
from .embeds import build_spread_embed
from .views import MarketPaginationView


class MarketCommands(EconomyBase):

    @commands.command(name="market", aliases=["m"])
    async def cmd_market(self, ctx: commands.Context) -> None:
        async with ctx.typing():
            if self._session is None:
                await ctx.send("❌ Session not ready.")
                return
            spreads = await mkt.fetch_all_spreads(self._session)
            # volume dari cache — diisi background job refresh_volume()
            # (main.py, tiap VOLUME_REFRESH_MIN=60 menit), jangan live-fetch
            volume = self._volume_cache
        if not spreads:
            await ctx.send("❌ Failed to fetch spread data.")
            return
        view         = MarketPaginationView(spreads, volume)
        view.message = await ctx.send(embed=build_spread_embed(spreads), view=view)
