"""
cogs/alerts/cmd_root.py  —  Root command group `xalert` + subgroup `xalert add`.

File cmd_add_*.py / cmd_list.py / dst mengimpor `cmd_alert` dan `alert_add`
dari sini untuk menempelkan subcommand masing-masing
(`@alert_add.command(...)` / `@cmd_alert.command(...)`). Ini meniru persis
cara kerja `commands.group()` di file asli — cuma sekarang group root-nya
didefinisikan satu kali di sini supaya bisa dipakai lintas file.
"""

from __future__ import annotations

from datetime import datetime

import discord
from discord.ext import commands

from .base import AlertsBase, GROUND_ALERT_THRESHOLD


class RootCommands(AlertsBase):

    @commands.group(name="alert", invoke_without_command=True, case_insensitive=True)
    async def cmd_alert(self, ctx: commands.Context) -> None:
        e = discord.Embed(title="🔔 Alert Commands", color=discord.Color.gold())
        e.description = (
            "**`xalert add war <country>`** — Alert when a country is at war\n"
            "   ↳ also auto-sends a **Ground Alert** if either side\n"
            f"   ↳ breaks >{GROUND_ALERT_THRESHOLD} ground points (once per round)\n"
            "**`xalert add order <country/MU>`** — Alert when a country/MU places a battle order\n"
            "**`xalert add bonus <resource>`** — Alert when the top production bonus changes\n"
            "   ↳ type `all` as the resource to watch all resources at once\n"
            "**`xalert add book <resource> [Nx]`** — Alert when the order book (top 3 price levels) is imbalanced\n"
            "   ↳ type `all` as the resource to watch all resources at once\n"
            "   ↳ add `Nx` at the end for a custom threshold (e.g. `iron 4x`), default 2x\n"
            "   ↳ 1 guild can only have 1 channel for all Order Book Alerts\n"
            "   ↳ alerts once, then again only if the imbalance flips side or after a 5h cooldown\n"
            "**`xalert list`** — View all active alerts\n"
            "**`xalert remove <id>`** — Remove an alert\n"
            "**`xalert test`** — Test-send a dummy alert\n"
            "**`xalert refresh`** — Manually refresh country cache"
        )
        e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
        await ctx.send(embed=e)

    @cmd_alert.group(name="add", invoke_without_command=True)
    async def alert_add(self, ctx: commands.Context) -> None:
        await ctx.send("Usage: `xalert add war <country>` or `xalert add order <country/MU>`")


# Alias level-modul supaya file cmd_add_*.py / cmd_list.py / dst tinggal
# `from .cmd_root import cmd_alert, alert_add` tanpa perlu inherit RootCommands.
cmd_alert = RootCommands.cmd_alert
alert_add = RootCommands.alert_add
