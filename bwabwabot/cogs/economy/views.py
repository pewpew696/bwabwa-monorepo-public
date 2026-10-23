"""
cogs/economy/views.py  —  Semua discord.ui.View (pagination) untuk Economy cog.
"""

from __future__ import annotations

import asyncio

from typing import Optional

import discord

from services import visuals as vis

from .embeds import (
    build_spread_embed,
    build_volume_embed,
    build_history_embed,
    build_bestime_embed,
    build_equipment_embed,
)


class MarketPaginationView(discord.ui.View):
    """Spread ↔ Volume — timeout 30 menit."""

    def __init__(self, spreads: list[dict], volume: dict[str, dict]) -> None:
        super().__init__(timeout=1800)
        self.page    = 1
        self.spreads = spreads
        self.volume  = volume
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        self.btn_spread.disabled = (self.page == 1)
        self.btn_volume.disabled = (self.page == 2)

    @discord.ui.button(label="Spread", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_spread(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 1; self._sync()
        await interaction.response.edit_message(embed=build_spread_embed(self.spreads), view=self)

    @discord.ui.button(label="Volume", style=discord.ButtonStyle.primary)
    async def btn_volume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 2; self._sync()
        await interaction.response.edit_message(embed=build_volume_embed(self.volume), view=self)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class HistoryPaginationView(discord.ui.View):
    """History ↔ Best Time — timeout 30 menit."""

    def __init__(self, name: str, days: int, data: list[dict], has_chart: bool = False) -> None:
        super().__init__(timeout=1800)
        self.page      = 1
        self.name      = name
        self.days      = days
        self.data      = data
        self.has_chart = has_chart
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        self.btn_history.disabled = (self.page == 1)
        self.btn_bestime.disabled = (self.page == 2)

    @discord.ui.button(label="History", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_history(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 1; self._sync()
        embed = build_history_embed(self.name, self.days, self.data)
        if self.has_chart:
            embed.set_image(url="attachment://chart.png")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Best Time", style=discord.ButtonStyle.primary)
    async def btn_bestime(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 2; self._sync()
        await interaction.response.edit_message(embed=build_bestime_embed(self.name, self.data), view=self)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class EquipmentPaginationView(discord.ui.View):
    """Crafting ↔ Dismantle — timeout 2 jam."""

    def __init__(self, price_scraps: float, price_steel: float) -> None:
        super().__init__(timeout=7200)
        self.page         = 1
        self.price_scraps = price_scraps
        self.price_steel  = price_steel
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        self.btn_craft.disabled    = (self.page == 1)
        self.btn_dismantle.disabled = (self.page == 2)

    @discord.ui.button(label="Crafting", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_craft(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 1; self._sync()
        await interaction.response.edit_message(embed=build_equipment_embed(1, self.price_scraps, self.price_steel), view=self)

    @discord.ui.button(label="Dismantle", style=discord.ButtonStyle.primary)
    async def btn_dismantle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 2; self._sync()
        await interaction.response.edit_message(embed=build_equipment_embed(2, self.price_scraps, self.price_steel), view=self)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class DonationPaginationView(discord.ui.View):
    """Halaman 1(+) = ranking mingguan, halaman berikutnya = tabel harian.
    Tiap ganti halaman, gambar di-generate ulang (bukan cuma ganti embed)
    karena isinya dikirim sebagai attachment PNG, bukan embed teks."""

    def __init__(self, country_name: str, page_specs: list[dict]) -> None:
        super().__init__(timeout=600)
        self.country_name = country_name
        self.page_specs    = page_specs
        self.index         = 0
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        self.btn_prev.disabled = (self.index == 0)
        self.btn_next.disabled = (self.index == len(self.page_specs) - 1)

    def _render(self) -> Optional[discord.File]:
        spec = self.page_specs[self.index]
        return vis.generate_donation_image(country_name=self.country_name, **spec)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_prev(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        self._sync()
        file = await asyncio.to_thread(self._render)
        if file is None:
            await interaction.response.send_message("❌ Failed to generate image.", ephemeral=True)
            return
        await interaction.response.edit_message(attachments=[file], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = min(len(self.page_specs) - 1, self.index + 1)
        self._sync()
        file = await asyncio.to_thread(self._render)
        if file is None:
            await interaction.response.send_message("❌ Failed to generate image.", ephemeral=True)
            return
        await interaction.response.edit_message(attachments=[file], view=self)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class WorkerProfitPaginationView(discord.ui.View):
    """Gross ↔ After Tax — timeout 30 menit. Kedua embed sudah di-precompute
    sebelum View dibuat (tidak ada fetch/hitung ulang saat tombol diklik)."""

    def __init__(self, embed_gross: discord.Embed, embed_tax: discord.Embed) -> None:
        super().__init__(timeout=1800)
        self.page        = 1
        self.embed_gross = embed_gross
        self.embed_tax   = embed_tax
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        active   = discord.ButtonStyle.success
        inactive = discord.ButtonStyle.secondary
        self.btn_gross.style    = active if self.page == 1 else inactive
        self.btn_gross.disabled = (self.page == 1)
        self.btn_tax.style      = active if self.page == 2 else inactive
        self.btn_tax.disabled   = (self.page == 2)

    @discord.ui.button(label="Gross", style=discord.ButtonStyle.success, disabled=True)
    async def btn_gross(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 1; self._sync()
        await interaction.response.edit_message(embed=self.embed_gross, view=self)

    @discord.ui.button(label="After Tax", style=discord.ButtonStyle.secondary)
    async def btn_tax(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.page = 2; self._sync()
        await interaction.response.edit_message(embed=self.embed_tax, view=self)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass
