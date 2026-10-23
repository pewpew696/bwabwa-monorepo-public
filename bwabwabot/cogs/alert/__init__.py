"""
cogs/alerts/  —  Battle Alert System (di-split per command dari alerts.py lama)

  Type 1: War Alert    — notifikasi saat negara target terlibat battle (attacker/defender)
  Type 2: Order Alert  — notifikasi saat negara/MU target pasang battle order
  Type 3: Bonus Alert  — notifikasi saat top-1 bonus produksi suatu resource berganti negara
  + Ground Alert (otomatis, nempel di Type 1) saat ground point > threshold

NOTE: war.getActiveWars TIDAK BISA dipakai API token (403 "API tokens cannot
access this endpoint"). Seluruh deteksi (Type 1 & 2) murni dari
region.getRegionsObject — field `activeBattle` tiap region.

Struktur:
  base.py           — konstanta, formatter, mixin AlertsBase (state, lifecycle,
                      db cache helper, data fetcher, flow interaktif "add")
  embeds.py         — build_war / orders / ground / bonus embed
  poll_war.py       — task loop poll_wars (Type 1 + Ground + Type 2, 1 fetch bersama)
  poll_bonus.py     — task loop poll_bonus (Type 3)
  cmd_root.py       — root group `xalert` (help) + subgrup `xalert add`
  cmd_add_remove.py — xalert add war/order/bonus + xalert remove
  cmd_list.py       — xalert list
  cmd_refresh.py    — xalert refresh
  cmd_test.py       — xalert test

Kenapa satu Cog banyak file — sama seperti cogs/economy/: discord.py menemukan
semua @commands.command di seluruh MRO class Cog akhir. Group root & subgroup
didefinisikan di cmd_root.py; file lain import objek Group itu dan menempel
subcommand lewat dekorator. Semua mixin digabung jadi `AlertsCog` di sini.
"""

from __future__ import annotations

from discord.ext import commands

from .base import AlertsBase
from .poll_war import PollWarCommands
from .poll_bonus import PollBonusCommands
from .poll_orderbook import PollOrderbookCommands
from .poll_storage import PollStorageCommands
from .cmd_storage import StorageWatchCommands
from .cmd_root import RootCommands
from .cmd_add_remove import AddWarCommands, AddOrderCommands, AddBonusCommands, AddOrderbookCommands, RemoveCommands
from .cmd_list import ListCommands
from .cmd_refresh import RefreshCommands
from .cmd_test import TestCommands


class AlertsCog(
    PollWarCommands,
    PollBonusCommands,
    PollOrderbookCommands,
    PollStorageCommands,
    RootCommands,
    AddWarCommands,
    AddOrderCommands,
    AddBonusCommands,
    AddOrderbookCommands,
    StorageWatchCommands,
    ListCommands,
    RemoveCommands,
    RefreshCommands,
    TestCommands,
    AlertsBase,
    commands.Cog,
):
    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AlertsCog(bot))
