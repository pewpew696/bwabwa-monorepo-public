"""
cogs/economy/  —  Economy commands (di-split per command dari economy.py lama)

Commands:
  xitem [name]                — Price + production bonus
  xprofit [AE]                — Daily profit ranking
  xorderbook <item>           — Full order book
  xmarket                     — Spread & Volume 24h (2 pages)
  xhistory <item> [days]      — Price history + best time to sell
  xtop [range]                — Top Gainers & Losers
  xfairprice [item] (xfp)     — Fair price analysis (1 item / list ringkas)
  xsetbonus <item> <%>        — Set manual bonus override
  xclearbonus [item]          — Remove override
  xoverrides                  — View active overrides
  xrefresh                    — Force refresh prices & bonuses
  xequipment                  — Equipment craft/dismantle calculator
  xdonation <country> [range] — Donor leaderboard (mingguan + tabel harian)

Struktur:
  base.py      — konstanta, formatter, mixin EconomyBase (shared state & helper)
  embeds.py    — pembangun discord.Embed / tabel teks
  views.py     — discord.ui.View (pagination)
  item/profit/orderbook/market/history/top/fairprice/bonus/refresh/
  equipment/donation.py — satu file per command

Kenapa banyak file: discord.py menemukan semua @commands.command di seluruh
MRO class Cog akhir. Jadi tiap file cukup jadi mixin (mewarisi EconomyBase,
BUKAN commands.Cog), dan semua digabung di satu EconomyCog yang didaftarkan
ke bot — satu command tetap satu Cog (satu instance, satu shared state).
"""

from __future__ import annotations

from discord.ext import commands

from .base import (
    EconomyBase,
    AE_PP_PER_DAY,
    ITEM_EMOJI,
    ITEM_NOT_PRODUCIBLE,
    PRODUCTION_CHAIN,
    TOP_RANGES,
    DONATION_RANGE_WEEKS,
    DON_PER_COL_CAP,
    DON_MAX_COLS,
    DON_PAGE_CAP,
)
from .item import ItemCommands
from .profit import ProfitCommands
from .orderbook import OrderbookCommands
from .market import MarketCommands
from .history import HistoryCommands
from .top import TopCommands
from .fairprice import FairPriceCommands
from .bonus import BonusCommands
from .refresh import RefreshCommands
from .equipment import EquipmentCommands
from .donation import DonationCommands
from .workerprofit import WorkerProfitCommands
from .dailyprofit import DailyProfitCommands


class EconomyCog(
    ItemCommands,
    ProfitCommands,
    OrderbookCommands,
    MarketCommands,
    HistoryCommands,
    TopCommands,
    FairPriceCommands,
    BonusCommands,
    RefreshCommands,
    EquipmentCommands,
    DonationCommands,
    WorkerProfitCommands,
    DailyProfitCommands,
    EconomyBase,
    commands.Cog,
    name="Economy",
):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))