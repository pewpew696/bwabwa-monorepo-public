"""
cogs/alerts/cmd_refresh.py  —  xalert refresh
"""

from __future__ import annotations

from discord.ext import commands

from .base import AlertsBase
from .cmd_root import cmd_alert


class RefreshCommands(AlertsBase):

    @cmd_alert.command(name="refresh")
    async def alert_refresh(self, ctx: commands.Context) -> None:
        async with ctx.typing():
            await self._refresh_country_cache(force_refresh=True)
        await ctx.send(f"✅ Country cache refreshed: `{len(self._country_cache)}` countries.")