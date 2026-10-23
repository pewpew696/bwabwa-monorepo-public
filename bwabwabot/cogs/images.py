"""
cogs/images.py  —  xguide / xg
  xguide          — tampilkan semua kategori sebagai tombol
  xguide <kategori> — langsung kirim image dari kategori tersebut
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import discord
from discord.ext import commands

from services.db import pool as db_pool

log = logging.getLogger("WarEraBot.images")


# --- HELPERS ---

from core.utils import _display_name
from core.utils import make_embed as _embed

# --- VIEWS ---

class CategoryView(discord.ui.View):
    """Tampilkan tombol per kategori. User pencet → kirim image kategori itu."""

    def __init__(self, categories: list[str], cog: "ImagesCog") -> None:
        super().__init__(timeout=300)
        self.cog = cog
        for cat in categories[:25]:  # Discord max 25 buttons per view
            btn = discord.ui.Button(
                label=_display_name(cat),
                style=discord.ButtonStyle.primary,
                custom_id=f"guide_{cat}",
            )
            btn.callback = self._make_callback(cat)
            self.add_item(btn)

    def _make_callback(self, category: str):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            images = await self.cog._get_images(category)
            if not images:
                await interaction.followup.send(
                    f"⚠️ No images in category **{_display_name(category)}**.",
                    ephemeral=True,
                )
                return

            # ✨ Kategori "war" punya alur khusus (disclaimer + WarLevelView),
            # sama seperti saat user ketik teks "xg war" secara manual.
            if category == "war":
                await self.cog._send_war_disclaimer(interaction.channel, images)
                return

            await self.cog._send_images(interaction.channel, category, images)
        return callback

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


class ImagesPaginationView(discord.ui.View):
    """Pagination untuk kategori yang punya lebih dari 1 image."""

    def __init__(self, category: str, images: list[dict]) -> None:
        super().__init__(timeout=300)
        self.category = category
        self.images   = images
        self.page     = 0
        self._sync()

    def _sync(self) -> None:
        self.btn_prev.disabled = self.page == 0
        self.btn_next.disabled = self.page >= len(self.images) - 1
        self.btn_label.label   = f"{self.page + 1} / {len(self.images)}"

    def _build_embed(self) -> discord.Embed:
        img = self.images[self.page]
        e   = _embed(
            f"📖 {_display_name(self.category)} — {_display_name(img['name'])}",
            discord.Color.blurple(),
        )
        e.set_image(url=img["url"])
        return e

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page -= 1
        self._sync()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_label(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page += 1
        self._sync()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


class WarLevelView(discord.ui.View):
    """
    View khusus untuk memilih level perang setelah membaca disclaimer.

    Tersusun menjadi 2 baris (masing-masing 4 tombol):
      Row 0 (hijau / success) → mode "sustain"
      Row 1 (merah  / danger)  → mode "burst"
    """

    def __init__(self, cog: "ImagesCog") -> None:
        super().__init__(timeout=300)
        self.cog = cog
        # 📌 Pesan output (hasil pilihan level) yang sedang aktif untuk view ini.
        # Hanya boleh ada 1 aktif dalam satu waktu — setiap kali user pencet
        # tombol level baru, pesan lama ini dihapus dulu sebelum kirim yang baru.
        self.output_message: discord.Message | None = None

    # --- Row 0 — Sustain (success / hijau) ---

    @discord.ui.button(label="Lvl 24-26", emoji="🌿", style=discord.ButtonStyle.success, row=0)
    async def btn_sustain_24_26(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_24_26_sustain", self)

    @discord.ui.button(label="Lvl 27-29", emoji="🌿", style=discord.ButtonStyle.success, row=0)
    async def btn_sustain_27_29(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_27_29_sustain", self)

    @discord.ui.button(label="Lvl 30-32", emoji="🌿", style=discord.ButtonStyle.success, row=0)
    async def btn_sustain_30_32(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_30_32_sustain", self)

    @discord.ui.button(label="Lvl 33-35", emoji="🌿", style=discord.ButtonStyle.success, row=0)
    async def btn_sustain_33_35(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_33_35_sustain", self)

    # --- Row 1 — Burst (danger / merah) ---

    @discord.ui.button(label="Lvl 24-26", emoji="🔥", style=discord.ButtonStyle.danger, row=1)
    async def btn_burst_24_26(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_24_26_burst", self)

    @discord.ui.button(label="Lvl 27-29", emoji="🔥", style=discord.ButtonStyle.danger, row=1)
    async def btn_burst_27_29(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_27_29_burst", self)

    @discord.ui.button(label="Lvl 30-32", emoji="🔥", style=discord.ButtonStyle.danger, row=1)
    async def btn_burst_30_32(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_30_32_burst", self)

    @discord.ui.button(label="Lvl 33-35", emoji="🔥", style=discord.ButtonStyle.danger, row=1)
    async def btn_burst_33_35(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog._send_level_images(interaction, "war_33_35_burst", self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# --- COG ---

class ImagesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # --- DB helpers ---

    async def _get_categories(self) -> list[str]:
        """
        Ambil semua kategori unik untuk ditampilkan di menu utama.

        Semua sub-kategori perang (mengandung "war_", mis. war_24_26_burst)
        disaring keluar — hanya kategori utama "war" (disclaimer) yang boleh
        muncul sebagai tombol publik.
        """
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("guide_images")
                    .select("category")
                    .execute()
                )
            )
            seen, cats = set(), []
            for row in (res or []):
                c = row["category"]
                # Sembunyikan seluruh sub-kategori level perang dari menu utama.
                # Kategori utama "war" (disclaimer) tetap boleh tampil.
                if "war_" in c:
                    continue
                if c not in seen:
                    seen.add(c)
                    cats.append(c)
            return sorted(cats)
        except Exception as exc:
            log.error(f"_get_categories: {exc}")
            return []

    async def _get_images(self, category: str) -> list[dict]:
        """Ambil semua image dari satu kategori."""
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("guide_images")
                    .select("name, url")
                    .eq("category", category.lower())
                    .order("created_at", desc=False)
                    .execute()
                )
            )
            return res or []
        except Exception as exc:
            log.error(f"_get_images({category}): {exc}")
            return []

    async def _resolve_category(self, query: str) -> str | None:
        """Cari kategori yang cocok (exact dulu, lalu partial)."""
        cats = await self._get_categories()
        q    = query.lower().replace(" ", "_")
        # Exact
        if q in cats:
            return q
        # Partial
        matches = [c for c in cats if q in c]
        return matches[0] if len(matches) == 1 else None

    # --- Send helpers ---

    async def _send_images(
        self,
        channel: discord.abc.Messageable,
        category: str,
        images: list[dict],
    ) -> discord.Message:
        """Kirim image ke channel. Kalau lebih dari 1, pakai pagination."""
        # Kalau channel di sini sebenarnya ctx (dipanggil dari command xguide,
        # bukan dari tombol kategori), auto-delete-nya sudah otomatis
        # dijadwalkan lewat patch ctx.send di main.py — nggak perlu queue lagi.
        is_ctx = isinstance(channel, commands.Context)

        if len(images) == 1:
            img = images[0]
            e   = _embed(
                f"📖 {_display_name(category)} — {_display_name(img['name'])}",
                discord.Color.blurple(),
            )
            e.set_image(url=img["url"])
            msg = await channel.send(embed=e)
        else:
            view = ImagesPaginationView(category, images)
            msg = await channel.send(embed=view._build_embed(), view=view)

        if not is_ctx:
            # Dipanggil dari tombol kategori (interaction.channel.send) —
            # jadwalkan hapus manual lewat Supabase queue (30 menit),
            # tahan restart bot, bukan delete_after bawaan discord.py.
            import main as bot_main
            await bot_main.queue_auto_delete(msg.channel.id, msg.id, 1800)

        return msg

    async def _send_war_disclaimer(
        self,
        channel: discord.abc.Messageable,
        images: list[dict],
    ) -> None:
        """
        Kirim gambar disclaimer kategori "war" beserta WarLevelView (8 tombol).
        Dipakai bersama oleh tombol kategori di menu utama (CategoryView) dan
        oleh cmd_guide() saat user ketik teks "xg war" secara manual.
        """
        is_ctx = isinstance(channel, commands.Context)

        view = WarLevelView(self)
        img  = images[0]
        e = _embed("📖 Disclaimer & Important War Notes", discord.Color.orange())
        e.set_image(url=img["url"])
        e.description = (
            "💡 **IMPORTANT: Please read the disclaimer in the image below first.**\n\n"
            "After reading it, choose the war guide for the level and mode "
            "you want using the buttons below:\n\n"
            "🌿 **Sustain** — green row\n"
            "🔥 **Burst** — red row"
        )
        msg = await channel.send(embed=e, view=view)

        if not is_ctx:
            import main as bot_main
            await bot_main.queue_auto_delete(msg.channel.id, msg.id, 1800)

    async def _send_level_images(
        self,
        interaction: discord.Interaction,
        category: str,
        view: "WarLevelView",
    ) -> None:
        """
        Callback bersama untuk kedelapan tombol WarLevelView.
        Menangani defer, pengambilan data Supabase, dan pengiriman gambar
        dengan penanganan error yang aman.

        Hanya 1 hasil level yang boleh aktif per view: sebelum kirim gambar
        level baru, hapus dulu pesan hasil level sebelumnya (jika ada).
        """
        try:
            await interaction.response.defer()
        except discord.HTTPException as exc:
            log.error(f"_send_level_images defer({category}): {exc}")
            return

        try:
            images = await self._get_images(category)
        except Exception as exc:
            log.error(f"_send_level_images fetch({category}): {exc}")
            await interaction.followup.send(
                "⚠️ An error occurred while fetching data from the database. Try again later.",
                ephemeral=True,
            )
            return

        if not images:
            await interaction.followup.send(
                f"⚠️ Guide images for **{_display_name(category)}** aren't available in the database yet.",
                ephemeral=True,
            )
            return

        # 🧹 Hapus pesan hasil level sebelumnya (kalau ada) supaya cuma 1
        # output yang aktif dalam satu waktu.
        if view.output_message is not None:
            try:
                await view.output_message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                log.warning(f"_send_level_images delete old output({category}): {exc}")
            finally:
                view.output_message = None

        try:
            msg = await self._send_images(interaction.channel, category, images)
            view.output_message = msg
        except Exception as exc:
            log.error(f"_send_level_images send({category}): {exc}")
            await interaction.followup.send(
                "⚠️ An error occurred while sending the image. Try again later.",
                ephemeral=True,
            )

    # --- xguide ---

    @commands.command(name="guide", aliases=["g"])
    async def cmd_guide(self, ctx: commands.Context, *, category: str = None) -> None:
        if category:
            category_lower = category.lower()

            # 🛑 BLOKIR: Cegah user mengetik langsung kategori/level perang secara
            # manual (mis. "war 24", "war lvl 24", "war_24_26_burst", dll.)
            # tanpa lebih dulu membaca disclaimer via "xg war".
            looks_like_war_level = (
                "war_" in category_lower
                or (
                    "war" in category_lower
                    and any(ch.isdigit() for ch in category_lower)
                )
                or (
                    "war" in category_lower
                    and any(kw in category_lower for kw in ["lvl", "level"])
                )
            )

            if looks_like_war_level:
                e = _embed("⚠️ Please Read the Disclaimer First", discord.Color.red())
                e.description = (
                    "You can't access war level guides directly.\n\n"
                    "Please type the **`xg war`** command first to read the important disclaimer, "
                    "then click the level button you want."
                )
                await ctx.send(embed=e)
                return

            # Cari kategori yang cocok
            resolved = await self._resolve_category(category)
            if not resolved:
                # Fallback jika user mengetik kata kunci "war" (tanpa angka/level)
                if category_lower.strip() == "war":
                    resolved = "war"
                else:
                    cats = await self._get_categories()
                    if cats:
                        cat_list = "\n".join(f"• `{_display_name(c)}`" for c in cats)
                        await ctx.send(
                            f"⚠️ Category `{category}` not found.\n\n"
                            f"**Available categories:**\n{cat_list}"
                        )
                    else:
                        await ctx.send("⚠️ No images saved yet.")
                    return

            async with ctx.typing():
                images = await self._get_images(resolved)
            if not images:
                await ctx.send(f"⚠️ No images in category **{_display_name(resolved)}**.")
                return

            # ✨ ALUR KHUSUS: Jika user mengakses kategori "war" (Disclaimer)
            if resolved == "war":
                await self._send_war_disclaimer(ctx, images)
                return

            # Kirim gambar kategori biasa lainnya
            await self._send_images(ctx, resolved, images)

        else:
            # Tampilkan semua kategori sebagai tombol
            async with ctx.typing():
                cats = await self._get_categories()

            if not cats:
                await ctx.send("⚠️ No images saved yet. Admins can add some with `xai`.")
                return

            # Summary per kategori
            lines = []
            for c in cats:
                images = await self._get_images(c)
                lines.append(f"• **{_display_name(c)}** ({len(images)} image)")

            e = _embed("📚 Guide Library", discord.Color.blurple())
            e.description = "\n".join(lines) + "\n\nChoose a category:"
            view = CategoryView(cats, self)
            await ctx.send(embed=e, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ImagesCog(bot))
