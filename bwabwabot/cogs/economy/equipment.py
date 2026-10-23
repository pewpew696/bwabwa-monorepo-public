"""
cogs/economy/equipment.py  —  xequipment  (Equipment craft/dismantle calculator)
"""

from __future__ import annotations

from discord.ext import commands

import market as mkt

from .base import EconomyBase
from .embeds import build_equipment_embed
from .views import EquipmentPaginationView


class EquipmentCommands(EconomyBase):

    @commands.command(name="equipment", aliases=["eq"])
    async def cmd_equipment(self, ctx: commands.Context) -> None:
        ps = self._price_cache.get("Scraps")
        pt = self._price_cache.get("Steel")
        if ps is None or pt is None:
            if self._session is None:
                await ctx.send("❌ Session not ready.")
                return
            async with ctx.typing():
                prices = await mkt.fetch_prices(self._session)
            if prices:
                self._price_cache.update(prices)
            ps = self._price_cache.get("Scraps")
            pt = self._price_cache.get("Steel")
        if ps is None or pt is None:
            await ctx.send("❌ Unable to fetch prices. Try `xrefresh` first.")
            return
        view         = EquipmentPaginationView(ps, pt)
        view.message = await ctx.send(embed=build_equipment_embed(1, ps, pt), view=view)
