# cogs/blocklist.py — kelola blocklist (spy & lain-lain nanti)

from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from core.blocklist import SPY_BLOCKLIST, add_block, list_block, remove_block
from core.permissions import LEVEL_BOT_ADMIN, get_level
from core.messages import MSG_NO_PERM_BOT_ADMIN
from services.spy.api_client import get_user_lite
from services.spy.search import find_player_exact
from core.utils import make_embed

log = logging.getLogger("WarEraBot.blocklist")

ID_PATTERN = re.compile(r"^[0-9a-fA-F]{24}$")


class BlocklistCog(commands.Cog):
    """xblock — kelola blocklist (Bot Admin only)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if await get_level(ctx.author) < LEVEL_BOT_ADMIN:
            await ctx.send(MSG_NO_PERM_BOT_ADMIN)
            return False
        return True

    # --- helper ---

    def _spy_cog(self):
        return self.bot.get_cog("SpyCog")

    async def _resolve_to_id(self, ctx: commands.Context, arg: str) -> str | None:
        """ID 24-hex dipakai apa adanya; selain itu dianggap usn dan di-resolve."""
        if ID_PATTERN.match(arg):
            return arg
        spy = self._spy_cog()
        if spy is None:
            await ctx.send("SpyCog tidak tersedia — nggak bisa resolve usn.")
            return None
        data, suggestions = await find_player_exact(self.bot._session, arg)
        if not data:
            msg = f"`{arg}` nggak ketemu."
            if suggestions:
                msg += " Mirip: " + ", ".join(f"`{s}`" for s in suggestions)
            await ctx.send(msg)
            return None
        return data.get("_id")

    async def _username_of(self, pid: str) -> str:
        spy = self._spy_cog()
        if spy is None:
            return "?"
        try:
            data = await get_user_lite(self.bot._session, pid)
            if data:
                return data.get("username", "?")
        except Exception as exc:
            log.error(f"_username_of({pid}): {exc}")
        return "?"

    # --- xblock (help) ---

    @commands.group(name="block", aliases=["blk"], invoke_without_command=True, case_insensitive=True)
    async def cmd_block(self, ctx: commands.Context) -> None:
        e = make_embed("🚫 Blocklist", discord.Color.dark_red())
        e.description = (
            "Prefix **`x`** — Bot Admin only\n\n"
            "**`xblock add <id|usn> [note]`**\n"
            "Tambah ke blocklist. Bisa pakai ID WarEra (24 hex) atau username.\n"
            "Example: `xblock add Vincapervinca alt-nya`\n\n"
            "**`xblock remove <id|usn>`**\n"
            "Hapus dari blocklist.\n"
            "Example: `xblock remove Vincapervinca`\n\n"
            "**`xblock list`**\n"
            "Lihat semua entry (usn di-resolve dari ID).\n"
        )
        await ctx.send(embed=e)

    # --- xblock add ---

    @cmd_block.command(name="add")
    async def cmd_add(self, ctx: commands.Context, arg: str, *, note: str = "") -> None:
        pid = await self._resolve_to_id(ctx, arg)
        if not pid:
            return
        ok = await add_block(SPY_BLOCKLIST, pid, str(ctx.author.id), note)
        if not ok:
            await ctx.send("Gagal nambah ke blocklist (lihat log).")
            return
        usn = await self._username_of(pid)
        e = make_embed("🚫 Ditambahkan", discord.Color.dark_red())
        e.add_field(name="ID", value=f"`{pid}`", inline=False)
        e.add_field(name="Username", value=usn, inline=True)
        if note:
            e.add_field(name="Note", value=note, inline=False)
        await ctx.send(embed=e)

    # --- xblock remove ---

    @cmd_block.command(name="remove", aliases=["rm"])
    async def cmd_remove(self, ctx: commands.Context, arg: str) -> None:
        pid = await self._resolve_to_id(ctx, arg)
        if not pid:
            return
        ok = await remove_block(SPY_BLOCKLIST, pid)
        if not ok:
            await ctx.send(f"`{pid}` nggak ada di blocklist.")
            return
        await ctx.send(f"✅ `{pid}` dihapus dari blocklist.")

    # --- xblock list ---

    @cmd_block.command(name="list", aliases=["ls"])
    async def cmd_list(self, ctx: commands.Context) -> None:
        rows = await list_block(SPY_BLOCKLIST)
        if not rows:
            await ctx.send("Blocklist kosong.")
            return
        lines = []
        limit = 20
        for r in rows[:limit]:
            pid = r.get("player_id", "?")
            usn = await self._username_of(pid)
            note = r.get("note") or ""
            tail = f" — {note}" if note else ""
            lines.append(f"`{pid}` **{usn}**{tail}")
        extra = len(rows) - limit
        desc = "\n".join(lines)
        if extra > 0:
            desc += f"\n… dan {extra} entry lain."
        e = make_embed(f"🚫 Blocklist ({len(rows)})", discord.Color.dark_red())
        e.description = desc
        await ctx.send(embed=e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BlocklistCog(bot))
