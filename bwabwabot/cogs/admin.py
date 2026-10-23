"""
cogs/admin.py  —  Admin-only commands
  xadmin / xa   — show admin help
  xaddimage     / xai  — upload image ke kategori
  xremoveimage  / xri  — hapus image dari kategori
  xaddadmin     / xaa  — tambah admin
  xremoveadmin  / xra  — hapus admin
  xdebug        / xdb  — status bot
  xreload       / xrl  — reload cog tanpa restart
  xannounce     / xan  — kirim pesan via bot ke channel tertentu

NOTE: xspy raw & xspy check (di cogs/spy.py) juga admin-only dan sudah
dicantumkan di embed xadmin di bawah, walau implementasinya ada di cog lain.

Supabase tables needed:
  bot_admins   : id (int), user_id (text)
  guide_images : id (int), category (text), name (text),
                 url (text), created_at (timestamptz)

Supabase Storage bucket needed:
  guide-images  (public bucket)
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands

from services.db import pool as db_pool

log = logging.getLogger("WarEraBot.admin")

# --- helpers ---

from core.permissions import OWNER_ID
from core.messages import MSG_NO_PERM_ADMIN
from core.utils import _display_name, make_embed as _embed

# --- cog ---

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def _session(self) -> aiohttp.ClientSession:
        return self.bot._session

    @property
    def _supabase_storage(self):
        return self.bot._supabase_storage

    # --- auth ---

    async def _is_admin(self, user_id: int) -> bool:
        from core.permissions import is_bot_admin
        return await is_bot_admin(user_id)

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not await self._is_admin(ctx.author.id):
            await ctx.send(MSG_NO_PERM_ADMIN)
            return False
        return True

    # --- xadmin (help) ---

    @commands.command(name="admin", aliases=["a"])
    async def cmd_admin(self, ctx: commands.Context) -> None:
        e = _embed("🛠️ Admin Commands", discord.Color.dark_gold())
        e.description = (
            "Prefix **`x`** or **`X`** — Owner & bot Admins only\n\n"

            "**── 🖼️ Image ──**\n"
            "**`xaddimage <category> <name>`**\n"
            "Alias: `xai`\n"
            "Upload an image to a category. Attach the image with the command.\n"
            "Example: `xai war_build Infantry_Build` + attachment\n\n"

            "**`xremoveimage <category> <name>`**\n"
            "Alias: `xri`\n"
            "Remove a single image from a category.\n"
            "Example: `xri war_build Infantry_Build`\n\n"

            "**── 👤 Admin ──**\n"
            "**`xaddadmin <user_id>`**\n"
            "Alias: `xaa`\n"
            "Add a new bot admin.\n"
            "Example: `xaa 123456789012345678`\n\n"

            "**`xremoveadmin <user_id>`**\n"
            "Alias: `xra`\n"
            "Remove a bot admin. The Owner cannot be removed.\n"
            "Example: `xra 123456789012345678`\n\n"

            "**── 🔍 War & Intel ──**\n"
            "**`xspy raw <name>`**\n"
            "Dump raw JSON from a player's profile — used to find unmapped "
            "fields (wealth breakdown, equipment durability, etc.).\n"
            "Example: `xspy raw Vincapervinca`\n\n"

            "**`xspy check <name>`**\n"
            "Compare a player's current wealth/damage snapshot against the "
            "last saved one to flag unusual gains.\n"
            "Example: `xspy check Vincapervinca`\n\n"

            "**── 🔧 Utility ──**\n"
            "**`xdebug`**\n"
            "Alias: `xdb`\n"
            "Bot status: uptime, cache, session.\n"
            "Example: `xdb`\n\n"

            "**`xreload <cog>`**\n"
            "Alias: `xrl`\n"
            "Reload a cog without restarting the bot.\n"
            "Example: `xrl alerts` | `xrl spy` | `xrl images` | `xrl admin` | "
            "`xrl economy` | `xrl help`\n\n"

            "**`xannounce <#channel> <message>`**\n"
            "Alias: `xan`\n"
            "Send a message via the bot to a specific channel.\n"
            "Example: `xan #general Server maintenance at 10 PM.`"
        )
        await ctx.send(embed=e)

    # --- xaddimage ---

    @commands.command(name="addimage", aliases=["ai"])
    async def cmd_addimage(
        self, ctx: commands.Context, category: str, name: str
    ) -> None:
        if not ctx.message.attachments:
            await ctx.send("⚠️ Attach an image with this command first.")
            return

        att = ctx.message.attachments[0]
        if not att.content_type or not att.content_type.startswith("image/"):
            await ctx.send("⚠️ File must be an image (jpg, png, gif, webp).")
            return

        # cek max 3 image per kategori
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("guide_images")
                    .select("id")
                    .eq("category", category.lower())
                    .execute()
                )
            )
            if len(res or []) >= 3:
                await ctx.send(
                    f"⚠️ Category `{_display_name(category)}` is full (max 3 images).\n"
                    f"Remove one first with `xri {category} <name>`."
                )
                return
        except Exception as exc:
            log.error(f"addimage check count: {exc}")
            await ctx.send("❌ Failed to check database.")
            return

        # cek duplikat nama
        try:
            res2 = await asyncio.to_thread(
                lambda: (
                    db_pool.table("guide_images")
                    .select("id")
                    .eq("category", category.lower())
                    .eq("name", name.lower())
                    .execute()
                )
            )
            if res2:
                await ctx.send(
                    f"⚠️ Image `{_display_name(name)}` already exists in category `{_display_name(category)}`."
                )
                return
        except Exception as exc:
            log.error(f"addimage check duplicate: {exc}")

        async with ctx.typing():
            # download image dari Discord
            try:
                async with self._session.get(att.url) as r:
                    if r.status != 200:
                        await ctx.send("❌ Failed to download image from Discord.")
                        return
                    image_bytes = await r.read()
            except Exception as exc:
                log.error(f"addimage download: {exc}")
                await ctx.send("❌ Failed to download image.")
                return

            # upload ke Supabase Storage
            ext          = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else "png"
            storage_path = f"{category.lower()}/{name.lower()}.{ext}"
            try:
                await asyncio.to_thread(
                    lambda: self._supabase_storage.storage.from_("guide-images").upload(
                        path=storage_path,
                        file=image_bytes,
                        file_options={"content-type": att.content_type or "image/png", "upsert": "true"},
                    )
                )
                public_url = self._supabase_storage.storage.from_("guide-images").get_public_url(storage_path)
            except Exception as exc:
                log.error(f"addimage upload storage: {exc}")
                await ctx.send("❌ Failed to upload to Supabase Storage.")
                return

            # simpan metadata ke tabel
            try:
                await asyncio.to_thread(
                    lambda: db_pool.table("guide_images").insert({
                        "category":   category.lower(),
                        "name":       name.lower(),
                        "url":        public_url,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
                )
            except Exception as exc:
                log.error(f"addimage insert db: {exc}")
                await ctx.send("❌ Failed to save to database.")
                return

        e = _embed("✅ Image Added", discord.Color.green())
        e.add_field(name="Category", value=_display_name(category), inline=True)
        e.add_field(name="Name",     value=_display_name(name),     inline=True)
        e.set_image(url=public_url)
        await ctx.send(embed=e)

    # --- xremoveimage ---

    @commands.command(name="removeimage", aliases=["ri"])
    async def cmd_removeimage(
        self, ctx: commands.Context, category: str, name: str
    ) -> None:
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("guide_images")
                    .select("id, url")
                    .eq("category", category.lower())
                    .eq("name", name.lower())
                    .execute()
                )
            )
            if not res:
                await ctx.send(
                    f"⚠️ Image `{_display_name(name)}` not found "
                    f"in category `{_display_name(category)}`."
                )
                return
            row = res[0]
        except Exception as exc:
            log.error(f"removeimage fetch: {exc}")
            await ctx.send("❌ Failed to fetch data.")
            return

        # hapus dari Storage
        ext          = row["url"].rsplit(".", 1)[-1].split("?")[0]
        storage_path = f"{category.lower()}/{name.lower()}.{ext}"
        try:
            await asyncio.to_thread(
                lambda: self._supabase_storage.storage.from_("guide-images").remove([storage_path])
            )
        except Exception as exc:
            log.warning(f"removeimage storage: {exc}")

        # hapus dari tabel
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("guide_images").delete().eq("id", row["id"]).execute()
            )
        except Exception as exc:
            log.error(f"removeimage db: {exc}")
            await ctx.send("❌ Failed to delete from database.")
            return

        await ctx.send(
            f"✅ Image **{_display_name(name)}** removed from category "
            f"**{_display_name(category)}**."
        )

    # --- xaddadmin ---

    @commands.command(name="addadmin", aliases=["aa"])
    async def cmd_addadmin(self, ctx: commands.Context, user_id: str) -> None:
        if not user_id.isdigit():
            await ctx.send("⚠️ User ID must be numeric.")
            return
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("bot_admins").upsert({"user_id": user_id}).execute()
            )
        except Exception as exc:
            log.error(f"addadmin: {exc}")
            await ctx.send("❌ Failed to add admin.")
            return

        user = await self.bot.fetch_user(int(user_id))
        name = user.name if user else user_id
        await ctx.send(f"✅ **{name}** (`{user_id}`) added as admin.")

    # --- xremoveadmin ---

    @commands.command(name="removeadmin", aliases=["ra"])
    async def cmd_removeadmin(self, ctx: commands.Context, user_id: str) -> None:
        if int(user_id) == OWNER_ID:
            await ctx.send("🚫 The Owner cannot be removed from admins.")
            return
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("bot_admins").delete().eq("user_id", user_id).execute()
            )
        except Exception as exc:
            log.error(f"removeadmin: {exc}")
            await ctx.send("❌ Failed to remove admin.")
            return

        await ctx.send(f"✅ User `{user_id}` removed from admin list.")

    # --- xdebug ---

    @commands.command(name="debug", aliases=["db"])
    async def cmd_debug(self, ctx: commands.Context) -> None:
        # ambil info dari bot
        session_ok = self._session is not None and not self._session.closed
        cogs_loaded = list(self.bot.cogs.keys())

        # hitung admin
        try:
            res = await asyncio.to_thread(
                lambda: db_pool.table("bot_admins").select("user_id").execute()
            )
            n_admins = len(res or [])
        except Exception:
            n_admins = -1

        # hitung image
        try:
            res2 = await asyncio.to_thread(
                lambda: db_pool.table("guide_images").select("id").execute()
            )
            n_imgs = len(res2 or [])
        except Exception:
            n_imgs = -1

        e = _embed("🔧 Debug — Bot Status", discord.Color.blurple())
        e.add_field(name="Session",      value="✅ OK" if session_ok else "❌ Closed", inline=True)
        e.add_field(name="Latency",      value=f"`{self.bot.latency*1000:.1f}ms`",    inline=True)
        e.add_field(name="Cogs Loaded",  value=", ".join(cogs_loaded) or "—",         inline=False)
        e.add_field(name="Admins",       value=f"`{n_admins}`",                        inline=True)
        e.add_field(name="Guide Images", value=f"`{n_imgs}`",                          inline=True)
        await ctx.send(embed=e)

    # --- xreload ---

    @commands.command(name="reload", aliases=["rl"])
    async def cmd_reload(self, ctx: commands.Context, cog: str) -> None:
        # NOTE: "economy" dan "help" sebelumnya ketinggalan di whitelist ini,
        # jadi xreload economy / xreload help selalu ditolak duluan.
        valid = {"economy", "spy", "alert", "images", "admin", "help"}
        cog_l = cog.lower()
        if cog_l not in valid:
            await ctx.send(f"⚠️ Unknown cog. Options: `{'`, `'.join(sorted(valid))}`")
            return
        ext = f"cogs.{cog_l}"
        try:
            await self.bot.reload_extension(ext)
            await ctx.send(f"✅ Cog `{cog_l}` reloaded successfully.")
        except Exception as exc:
            log.error(f"reload {ext}: {exc}")
            await ctx.send(f"❌ Failed to reload `{cog_l}`: `{exc}`")

    # --- xannounce ---

    @commands.command(name="announce", aliases=["an"])
    async def cmd_announce(
        self, ctx: commands.Context, channel: discord.TextChannel, *, message: str
    ) -> None:
        # command message user langsung dihapus (bukan auto-delete 30 menit
        # seperti command lain)
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        try:
            # output di channel tujuan TIDAK memakai delete_after -- permanen
            await channel.send(message)
            await ctx.send(f"✅ Message sent to {channel.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ Bot doesn't have permission to send messages to that channel.")
        except Exception as exc:
            log.error(f"announce: {exc}")
            await ctx.send("❌ Failed to send message.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
