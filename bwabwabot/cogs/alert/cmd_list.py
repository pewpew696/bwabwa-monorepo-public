"""
cogs/alerts/cmd_list.py  —  xalert list
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import discord
from discord.ext import commands

from .base import AlertsBase
from .cmd_root import cmd_alert

from services.db import pool as db_pool


class ListCommands(AlertsBase):

    @cmd_alert.command(name="list")
    async def alert_list(self, ctx: commands.Context) -> None:
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("alert_configs")
                    .select("*")
                    .eq("guild_id", str(ctx.guild.id))
                    .execute()
                )
            )
            rows = res or []
        except Exception as exc:
            await ctx.send("❌ Failed to fetch data.")
            return

        if not rows:
            await ctx.send("ℹ️ No alerts in this server yet.")
            return

        e = discord.Embed(title="🔔 Alert Configs", color=discord.Color.gold())
        type_labels = {1: "⚔️ War Alert", 2: "📋 Order Alert", 3: "🏭 Production Bonus Alert"}
        for row in rows:
            type_label = type_labels.get(row["alert_type"], "❓ Unknown")
            channel    = self.bot.get_channel(int(row["channel_id"]))
            ch_str     = channel.mention if channel else f"#{row['channel_id']}"
            ping_str   = " ".join(f"<@&{rid}>" for rid in row["role_ping"].split(",") if rid) if row.get("role_ping") else "—"
            e.add_field(
                name=f"ID {row['id']} — {type_label}",
                value=(
                    f"Target: **{row['target_name']}** ({row['target_type']})\n"
                    f"Channel: {ch_str}\n"
                    f"Ping: {ping_str}"
                ),
                inline=False,
            )
        e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
        await ctx.send(embed=e)