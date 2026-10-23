"""
cogs/economy/history.py  —  xhistory <item> [days]  (Price history + best time to sell)
"""

from __future__ import annotations
from services.economy.db_history import get_price_history

import asyncio

from discord.ext import commands

from services import visuals as vis

from .base import EconomyBase
from .embeds import build_history_embed
from .views import HistoryPaginationView


class HistoryCommands(EconomyBase):

    @commands.command(name="history", aliases=["hist"])
    async def cmd_history(self, ctx: commands.Context, item: str, days: int = 7) -> None:
        if days < 7 or days > 30:
            await ctx.send("⚠️ Period must be between 7-30 days.")
            return
        name = self._resolve(item)
        if name is None:
            await ctx.send(f"Item `{item}` not found.")
            return
        async with ctx.typing():
            data = await get_price_history(name, hours=days * 24)
        if not data:
            await ctx.send(f"⚠️ No history data for `{name}` yet.")
            return
        embed = build_history_embed(name, days, data)
        chart = await asyncio.to_thread(vis.generate_price_chart, name, data, days)
        view  = HistoryPaginationView(name, days, data, has_chart=(chart is not None))
        if chart is not None:
            embed.set_image(url="attachment://chart.png")
            view.message = await ctx.send(embed=embed, file=chart, view=view)
        else:
            view.message = await ctx.send(embed=embed, view=view)
