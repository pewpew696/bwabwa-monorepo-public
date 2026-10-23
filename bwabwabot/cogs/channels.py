"""
cogs/channels.py — Per-server channel restriction (allowlist)
  xchannel / xch  — allow/deny/list/reset

Kosong (belum ada entry utk guild ini) = bot bebas dipakai di semua channel.
Begitu ada 1+ entry = restricted, bot cuma respon di channel yang di-allow.

Alert push (channel.send langsung dari task/alert system) TIDAK terpengaruh
sama sekali — restriksi ini cuma jalan lewat bot.check, yang cuma dicek
untuk command yang diketik user, bukan pesan yang bot kirim sendiri.

Supabase/PG table needed:
  allowed_channels : guild_id (text), channel_id (text)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from services.db import pool as db_pool
import discord
from discord.ext import commands

from core.utils import make_embed as _embed
from core.permissions import OWNER_ID, is_bot_admin
from core.messages import MSG_NO_PERM_SERVER

log = logging.getLogger("WarEraBot.channels")

EXEMPT_COMMANDS = {"channel"}


class ChannelsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.allowed: dict[str, set[int]] = defaultdict(set)

    async def cog_load(self) -> None:
        await self._load_from_db()

    async def _can_manage(self, ctx: commands.Context) -> bool:
        if ctx.author.id == OWNER_ID:
            return True
        if await is_bot_admin(ctx.author.id):
            return True
        return bool(ctx.author.guild_permissions.administrator)

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not await self._can_manage(ctx):
            await ctx.send(MSG_NO_PERM_SERVER)
            return False
        return True

    async def _load_from_db(self) -> None:
        try:
            res = await asyncio.to_thread(
                lambda: db_pool.table("allowed_channels").select("*").execute()
            )
        except Exception as exc:
            log.error(f"channels _load_from_db: {exc}")
            return
        self.allowed.clear()
        for row in (res or []):
            self.allowed[row["guild_id"]].add(int(row["channel_id"]))
        self.bot._allowed_channels = self.allowed
        log.info(f"allowed_channels loaded: {len(res or [])} rows, {len(self.allowed)} guild(s) restricted")

    async def _add(self, guild_id: int, channel_id: int) -> None:
        await asyncio.to_thread(
            lambda: db_pool.table("allowed_channels").upsert(
                {"guild_id": str(guild_id), "channel_id": str(channel_id)},
                on_conflict="guild_id,channel_id",
            ).execute()
        )
        self.allowed[str(guild_id)].add(channel_id)

    async def _remove(self, guild_id: int, channel_id: int) -> None:
        await asyncio.to_thread(
            lambda: db_pool.table("allowed_channels")
            .delete()
            .eq("guild_id", str(guild_id))
            .eq("channel_id", str(channel_id))
            .execute()
        )
        self.allowed[str(guild_id)].discard(channel_id)

    async def _reset(self, guild_id: int) -> None:
        await asyncio.to_thread(
            lambda: db_pool.table("allowed_channels")
            .delete()
            .eq("guild_id", str(guild_id))
            .execute()
        )
        self.allowed.pop(str(guild_id), None)

    @commands.group(name="channel", aliases=["ch"], invoke_without_command=True)
    async def channel_group(self, ctx: commands.Context) -> None:
        e = _embed("🔒 Channel Restriction", discord.Color.dark_gold())
        e.description = (
            "Prefix **`x`** — Server admins & bot admins only\n\n"
            "**`xchannel allow [#channel]`**\n"
            "Allow the bot to respond here (or in the given channel/VC).\n"
            "First `allow` in a server switches it into restricted mode.\n\n"
            "**`xchannel deny [#channel]`**\n"
            "Remove a channel from the allowlist.\n\n"
            "**`xchannel list`**\n"
            "Show every channel currently allowed in this server.\n\n"
            "**`xchannel reset`**\n"
            "Clear the allowlist entirely — bot becomes usable everywhere "
            "again in this server."
        )
        await ctx.send(embed=e)

    @channel_group.command(name="allow")
    async def channel_allow(
        self, ctx: commands.Context, channel: discord.abc.GuildChannel = None
    ) -> None:
        channel = channel or ctx.channel
        await self._add(ctx.guild.id, channel.id)
        await ctx.send(f"✅ Bot commands now allowed in {channel.mention}.")

    @channel_group.command(name="deny")
    async def channel_deny(
        self, ctx: commands.Context, channel: discord.abc.GuildChannel = None
    ) -> None:
        channel = channel or ctx.channel
        await self._remove(ctx.guild.id, channel.id)
        await ctx.send(f"❌ Bot commands no longer allowed in {channel.mention}.")

    @channel_group.command(name="list")
    async def channel_list(self, ctx: commands.Context) -> None:
        ids = self.allowed.get(str(ctx.guild.id))
        if not ids:
            await ctx.send("🔓 No restriction set — bot works in every channel here.")
            return
        mentions = ", ".join(f"<#{i}>" for i in ids)
        await ctx.send(f"🔒 Allowed channels: {mentions}")

    @channel_group.command(name="reset")
    async def channel_reset(self, ctx: commands.Context) -> None:
        await self._reset(ctx.guild.id)
        await ctx.send("♻️ Restriction cleared — bot works in every channel here again.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChannelsCog(bot))
