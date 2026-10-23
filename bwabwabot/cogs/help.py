"""
cogs/help.py  —  xhelp
Gaya baru: menu kategori berbentuk tombol, tiap tombol nampilin embed kategorinya.
"""

from __future__ import annotations

import discord
from discord.ext import commands
from datetime import datetime


from core.utils import make_embed as _embed


CATEGORIES: dict[str, dict] = {
    "economy": {
        "label": "💰 Economy",
        "title": "💰 Economy",
        "description": (
            "**`xitem [name]`**\n"
            "Alias: `xi`\n"
            "Price + highest Production Bonus. No arg = all items.\n"
            "Item name can skip spaces, e.g. `case1`/`case2`/`plant`/`cooked`.\n"
            "Example: `xitem iron` | `xitem case1` | `xitem`\n\n"

            "**`xprofit [AE]`**\n"
            "Alias: `xp`\n"
            "Daily Profit ranking with production chain & input cost.\n"
            "Example: `xprofit 6` | `xp 4`\n\n"

            "**`xorderbook <item>`**\n"
            "Alias: `xob`\n"
            "Full Order Book — all Bid/Ask levels, aggregated.\n"
            "Example: `xorderbook iron` | `xob light ammo`\n\n"

            "**`xmarket`**\n"
            "Alias: `xm`\n"
            "Real-time Spread & 24h Volume (2 pages, button 30 min).\n"
            "Example: `xmarket` | `xm`\n\n"

            "**`xhistory <item> [days]`**\n"
            "Alias: `xhist`\n"
            "Price history + best time to sell (7-30 days, default 7).\n"
            "Item name can skip spaces, e.g. `case1`/`case2`/`plant`/`cooked`.\n"
            "Example: `xhistory iron` | `xhist case1 30`\n\n"

            "**`xtop [range]`**\n"
            "Alias: `xt`\n"
            "Top Gainers & Losers based on price history.\n"
            "Example: `xtop` | `xtop 7d` | `xtop 30d`\n\n"

            "**`xsetbonus <item> <%>`**\n"
            "Alias: `xsb`\n"
            "Set manual Production Bonus override (auto-expires 1h).\n"
            "Example: `xsetbonus iron 65` | `xsb grain 30`\n\n"

            "**`xoverrides`**\n"
            "View all active manual overrides.\n"
            "Example: `xoverrides`\n\n"

            "**`xclearbonus [item]`**\n"
            "Alias: `xcb`\n"
            "Remove manual override. No arg = clear all.\n"
            "Example: `xclearbonus iron` | `xcb`\n\n"

            "**`xequipment`**\n"
            "Alias: `xeq`\n"
            "Equipment crafting cost & dismantle value calculator.\n"
            "Example: `xequipment` | `xeq`\n\n"

            "**`xfairprice [item]`**\n"
            "Alias: `xfp`\n"
            "Fair price analysis — Cost/Valuation/Market/Recommendation. No arg = quick list of all items (sorted by Expected Edge).\n"
            "Example: `xfairprice iron` | `xfp`\n\n"

            "**`xdonation <country> [range]`**\n"
            "Alias: `xdon` `xdonate`\n"
            "Country donor leaderboard per weekly range (1w–5w, default 1w).\n"
            "Example: `xdonation Laos 2w` | `xdon Laos`\n\n"
            "**`xworkerprofit`**\n"
            "Alias: `xwp`\n"
            "Top 10 items most profitable to hire a worker for (wage vs sell price + raw cost, using highest Production Bonus + fidelity).\n"
            "Example: `xworkerprofit` | `xwp`\n\n"

            "**`xdailyprofit <username> [item]`**\n"
            "Alias: `xdp`\n"
            "Estimated daily profit for 1 player from real data (companies, region bonus, own wage). Optional item arg picks which company gets the entrepreneurship action.\n"
            "Example: `xdailyprofit Vincapervinca` | `xdp Vincapervinca iron`"
        ),
    },
    "war": {
        "label": "⚔️ War & Intel",
        "title": "⚔️ War & Intel",
        "description": (
            "**`xspy player <name>`**\n"
            "Alias: `xspy p`\n"
            "Player intel: stats, gear, burst dmg, pill status, HP.\n"
            "Example: `xspy player Vincapervinca`\n\n"

            "**`xspy country <name>`**\n"
            "Alias: `xspy c`\n"
            "Country intel: government, region, company index cache.\n"
            "Example: `xspy country Laos`\n\n"

            "**`xspy mu <name>`**\n"
            "Alias: `xspy m`\n"
            "Military Unit roster: level, role, build, HP, hunger, pill.\n"
            "Example: `xspy mu 10th Para SF`\n\n"

            "**`xspy trade <name>`**\n"
            "Alias: `xspy wr` `xspy winrate`\n"
            "Win rate trading (FIFO cost-basis matching), net profit & most profitable/losing item.\n"
            "Example: `xspy trade Vincapervinca`\n\n"

            "**`xspy check <name>`**\n"
            "Daily growth: dmg & wealth vs yesterday's snapshot. Checked players are automatically added to tracking.\n"
            "Example: `xspy check Vincapervinca`\n\n"

            "**`xspy scan`** 🔒 Admin only\n"
            "Progress bar background scan company_index.\n"
            "Example: `xspy scan`\n\n"

            "**`xspy raw <name>`** 🔒 Admin only\n"
            "Dump raw player JSON data (debug).\n"
            "Example: `xspy raw Vincapervinca`\n\n"

            
        ),
    },
    "utility": {
        "label": "🛠️ Utility",
        "title": "🛠️ Utility",
        "description": (
            "**`xrefresh`**\n"
            "Alias: `xr`\n"
            "Force update prices & Production Bonus now.\n"
            "Example: `xrefresh` | `xr`"
        ),
    },
    
    "alert": {
        "label": "🔔 Alerts",
        "title": "🔔 Alerts",
        "description": (
"**`xalert add war <country>`**\n"
            "Set alert when a country is involved in war.\n"
            "Example: `xalert add war Laos`\n\n"

            "**`xalert add order <country/MU>`**\n"
            "Set alert when a country or MU places a battle order.\n"
            "Example: `xalert add order Laos` | `xalert add order 10th Para SF`\n\n"

            "**`xalert add bonus <resource>`**\n"
            "Set alert when a resource's highest Production Bonus changes.\n"
            "Example: `xalert add bonus iron`\n\n"
            "**`xalert add book <item> [Nx]`**\n"
            "Alert when order book (best bid/ask) is imbalanced. `all` = all items, `Nx` = custom threshold (default 2x).\n"
            "Example: `xalert add book iron` | `xalert add book iron 4x` | `xalert add book all`\n\n"

            "**`xalert list`**\n"
            "View all active alerts in this server.\n"
            "Example: `xalert list`\n\n"

            "**`xalert remove <id>`**\n"
            "Alias: `xalert delete` `xalert del`\n"
            "Remove an alert by ID.\n"
            "Example: `xalert remove 3`\n\n"

            "**`xalert refresh`**\n"
            "Force refresh country name cache used for alert matching.\n"
            "Example: `xalert refresh`\n\n"

            "**`xalert test`**\n"
            "Send a dummy alert to this channel.\n"
            "Example: `xalert test`"
        ),
    },
}


class HelpView(discord.ui.View):
    def __init__(self, author_id: int, *, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.message: discord.Message | None = None

        for key, data in CATEGORIES.items():
            self.add_item(self._make_button(key, data["label"]))

        self.add_item(self._make_home_button())

    def _make_button(self, key: str, label: str) -> discord.ui.Button:
        button: discord.ui.Button = discord.ui.Button(
            label=label, style=discord.ButtonStyle.secondary, custom_id=f"help_cat_{key}"
        )

        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "This isn't your menu. Type `xhelp` yourself.", ephemeral=True
                )
                return
            data = CATEGORIES[key]
            e = _embed(data["title"])
            e.description = data["description"]
            await interaction.response.edit_message(embed=e, view=self)

        button.callback = callback
        return button

    def _make_home_button(self) -> discord.ui.Button:
        button: discord.ui.Button = discord.ui.Button(
            label="🏠 Home", style=discord.ButtonStyle.primary, custom_id="help_home"
        )

        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "This isn't your menu. Type `xhelp` yourself.", ephemeral=True
                )
                return
            await interaction.response.edit_message(embed=_home_embed(), view=self)

        button.callback = callback
        return button

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


def _home_embed() -> discord.Embed:
    e = _embed("📖 bwabwabwa — Help")
    e.description = (
        "Prefix **`x`** or **`X`**\n\n"
        "Pick a category below to see its commands:\n\n"
        + "\n".join(f"{data['label']}" for data in CATEGORIES.values())
    )
    return e


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help")
    async def cmd_help(self, ctx: commands.Context) -> None:
        view = HelpView(author_id=ctx.author.id)
        view.message = await ctx.send(embed=_home_embed(), view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Help(bot))
