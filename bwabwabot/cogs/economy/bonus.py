"""
cogs/economy/bonus.py  —  xsetbonus <item> <%> / xclearbonus [item] / xoverrides
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord.ext import commands

from services.economy.formatters import _fmt_pct, _format_remaining
from .base import EconomyBase, _embed


class BonusCommands(EconomyBase):

    @commands.command(name="setbonus", aliases=["sb"])
    async def cmd_setbonus(self, ctx: commands.Context, item: str, percent: float) -> None:
        resolved   = self._resolve(item) or item.title()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=60)
        self._manual_overrides[resolved] = {"pct": percent, "expires_at": expires_at}
        e = _embed("✅ Production Bonus Override Saved", discord.Color.green())
        e.add_field(name="Item",             value=f"`{resolved}`",              inline=True)
        e.add_field(name="Production Bonus", value=f"**+{_fmt_pct(percent)}%**", inline=True)
        e.add_field(name="Expires in",       value="60 min",                     inline=True)
        await ctx.send(embed=e)

    @commands.command(name="clearbonus", aliases=["cb"])
    async def cmd_clearbonus(self, ctx: commands.Context, *, item: Optional[str] = None) -> None:
        if item is None:
            count = len(self._manual_overrides)
            self._manual_overrides.clear()
            await ctx.send(f"✅ All overrides ({count} items) cleared.")
            return
        resolved = next((k for k in self._manual_overrides if k.lower() == item.lower()), None)
        if resolved is None:
            await ctx.send(f"⚠️ No active override for `{item}`.")
            return
        del self._manual_overrides[resolved]
        await ctx.send(f"✅ Override for `{resolved}` removed.")

    @commands.command(name="overrides")
    async def cmd_overrides(self, ctx: commands.Context) -> None:
        self._cleanup_overrides()
        if not self._manual_overrides:
            await ctx.send("ℹ️ No active overrides.")
            return
        e = _embed("🔧 Active Manual Overrides", discord.Color.orange())
        e.description = "\n".join(
            f"`{k:<16}` **+{_fmt_pct(v['pct'])}%**  — expires in {_format_remaining(v['expires_at'])}"
            for k, v in sorted(self._manual_overrides.items())
        )
        await ctx.send(embed=e)
