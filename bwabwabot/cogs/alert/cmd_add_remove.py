"""
cogs/alerts/cmd_add_remove.py  —  xalert add war/order/bonus + xalert remove <id>

Digabung dalam satu file karena semuanya soal "menambah/menghapus" alert
config — lebih gampang dilihat berdampingan dibanding tersebar per file.
"""

from __future__ import annotations

import asyncio
from services.db import pool as db_pool
import re
from datetime import datetime

import discord
from discord.ext import commands

from .base import AlertsBase, log, _resolve_resource
from .cmd_root import cmd_alert, alert_add


class AddWarCommands(AlertsBase):

    @alert_add.command(name="war")
    async def alert_add_war(self, ctx: commands.Context, *, target: str) -> None:
        await self._interactive_add(ctx, alert_type=1, target_name=target)


class AddOrderCommands(AlertsBase):

    @alert_add.command(name="order")
    async def alert_add_order(self, ctx: commands.Context, *, target: str) -> None:
        await self._interactive_add(ctx, alert_type=2, target_name=target)


class AddBonusCommands(AlertsBase):

    @alert_add.command(name="bonus")
    async def alert_add_bonus(self, ctx: commands.Context, *, resource: str) -> None:
        await self._interactive_add_bonus(ctx, resource)

    async def _interactive_add_bonus(self, ctx: commands.Context, resource: str) -> None:
        resource_clean = resource.strip().lower()

        if resource_clean in ("all", "semua"):
            item_id, item_label = "all", "All Resources"
        else:
            resolved = _resolve_resource(resource)
            if not resolved:
                await ctx.send(f"⚠️ Resource `{resource}` not recognized.")
                return
            item_id, item_label = resolved

        await ctx.send(
            f"✅ Target: **{item_label}** (Production Bonus)\n"
            f"📌 Type the **#channel** for this alert:"
        )

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timeout.")
            return

        channel = None
        if msg.channel_mentions:
            channel = msg.channel_mentions[0]
        else:
            name    = msg.content.strip().lstrip("#")
            channel = discord.utils.get(ctx.guild.text_channels, name=name)

        if not channel:
            await ctx.send("⚠️ Channel not found.")
            return

        await ctx.send("🔔 Type **@role** to ping, or type `skip`:")
        try:
            msg2 = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            msg2 = None

        role_ping = None
        if msg2 and msg2.content.strip().lower() != "skip" and msg2.role_mentions:
            role_ping = ",".join(str(r.id) for r in msg2.role_mentions)

        try:
            await asyncio.to_thread(
                lambda: db_pool.table("alert_configs").insert({
                    "guild_id":    str(ctx.guild.id),
                    "alert_type":  3,
                    "target_type": "resource",
                    "target_id":   item_id,
                    "target_name": item_label,
                    "channel_id":  str(channel.id),
                    "role_ping":   role_ping,
                }).execute()
            )
        except Exception as exc:
            log.error(f"alert_add_bonus save: {exc}")
            await ctx.send("❌ Failed to save.")
            return

        e = discord.Embed(title="✅ Alert Saved", color=discord.Color.green())
        e.add_field(name="Type",       value="🏭 Production Bonus Alert", inline=True)
        e.add_field(name="Target",     value=item_label,     inline=True)
        e.add_field(name="Channel",    value=channel.mention, inline=True)
        e.add_field(
            name="Role Ping",
            value=" ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) if role_ping else "—",
            inline=True,
        )
        e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
        await ctx.send(embed=e)


_RATIO_RE = re.compile(r"^(\d+(?:\.\d+)?)x$", re.IGNORECASE)


class AddOrderbookCommands(AlertsBase):

    @alert_add.command(name="book")
    async def alert_add_book(self, ctx: commands.Context, *, target: str) -> None:
        await self._interactive_add_orderbook(ctx, target)

    async def _interactive_add_orderbook(self, ctx: commands.Context, target: str) -> None:
        parts = target.strip().split()
        custom_ratio = None
        if parts and _RATIO_RE.match(parts[-1]):
            custom_ratio = float(_RATIO_RE.match(parts[-1]).group(1))
            parts = parts[:-1]
        resource = " ".join(parts).strip()

        resource_clean = resource.lower()
        if resource_clean in ("all", "semua"):
            item_id, item_label = "all", "All Resources"
        else:
            resolved = _resolve_resource(resource)
            if not resolved:
                await ctx.send(f"⚠️ Resource `{resource}` not recognized.")
                return
            item_id, item_label = resolved

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel

        # 1 guild = 1 channel untuk seluruh Order Book Alert. Kalau guild ini
        # sudah punya baris alert_type=4 lain, reuse channel-nya -- jangan
        # tanya lagi (mencegah 1 guild punya >1 channel utk fitur ini).
        existing = await self._get_configs(4)
        existing_guild = [c for c in existing if c["guild_id"] == str(ctx.guild.id)]

        if existing_guild:
            channel = self.bot.get_channel(int(existing_guild[0]["channel_id"]))
            if not channel:
                await ctx.send("⚠️ The previous Order Book Alert channel could no longer be found (maybe deleted). Contact an admin to remove the old config first via `xalert remove`.")
                return
            await ctx.send(
                f"✅ Target: **{item_label}** (Order Book Imbalance"
                + (f", custom threshold `{custom_ratio}x`" if custom_ratio else "")
                + f")\nℹ️ This guild already uses {channel.mention} for other Order Book Alerts — reusing it automatically."
            )
        else:
            await ctx.send(
                f"✅ Target: **{item_label}** (Order Book Imbalance"
                + (f", custom threshold `{custom_ratio}x`" if custom_ratio else "")
                + ")\n📌 Type the **#channel** for this alert (applies to ALL Order Book Alerts in this guild):"
            )
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Timeout.")
                return

            channel = None
            if msg.channel_mentions:
                channel = msg.channel_mentions[0]
            else:
                name    = msg.content.strip().lstrip("#")
                channel = discord.utils.get(ctx.guild.text_channels, name=name)

            if not channel:
                await ctx.send("⚠️ Channel not found.")
                return

        await ctx.send("🔔 Type **@role** to ping, or type `skip`:")
        try:
            msg2 = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            msg2 = None

        role_ping = None
        if msg2 and msg2.content.strip().lower() != "skip" and msg2.role_mentions:
            role_ping = ",".join(str(r.id) for r in msg2.role_mentions)

        try:
            await asyncio.to_thread(
                lambda: db_pool.table("alert_configs").insert({
                    "guild_id":     str(ctx.guild.id),
                    "alert_type":   4,
                    "target_type":  "resource",
                    "target_id":    item_id,
                    "target_name":  item_label,
                    "channel_id":   str(channel.id),
                    "role_ping":    role_ping,
                    "custom_ratio": custom_ratio,
                }).execute()
            )
        except Exception as exc:
            log.error(f"alert_add_book save: {exc}")
            await ctx.send("❌ Failed to save.")
            return

        e = discord.Embed(title="✅ Alert Saved", color=discord.Color.green())
        e.add_field(name="Type",    value="⚖️ Order Book Alert", inline=True)
        e.add_field(name="Target",  value=item_label, inline=True)
        e.add_field(name="Threshold",  value=f"`{custom_ratio}x`" if custom_ratio else "Default", inline=True)
        e.add_field(name="Channel", value=channel.mention, inline=True)
        e.add_field(
            name="Role Ping",
            value=" ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) if role_ping else "—",
            inline=True,
        )
        e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
        await ctx.send(embed=e)


class RemoveCommands(AlertsBase):

    @cmd_alert.command(name="remove", aliases=["delete", "del"])
    async def alert_remove(self, ctx: commands.Context, alert_id: int) -> None:
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("alert_configs")
                    .select("id, target_name, alert_type")
                    .eq("id", alert_id)
                    .eq("guild_id", str(ctx.guild.id))
                    .execute()
                )
            )
            if not res:
                await ctx.send(f"⚠️ Alert ID `{alert_id}` not found.")
                return
            row = res[0]
            await asyncio.to_thread(
                lambda: db_pool.table("alert_configs").delete().eq("id", alert_id).execute()
            )
            type_label = {1: "War Alert", 2: "Order Alert", 3: "Production Bonus Alert", 4: "Order Book Alert"}.get(
                row["alert_type"], "Alert"
            )
            await ctx.send(
                f"✅ `{type_label}` for **{row['target_name']}** (ID {alert_id}) removed."
            )
        except Exception as exc:
            log.error(f"alert_remove: {exc}")
            await ctx.send("❌ Failed to delete.")
