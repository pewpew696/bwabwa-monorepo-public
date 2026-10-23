"""
cogs/spy/__init__.py  —  xspy player <n> | xspy mu <name_or_id> | dst.

File ini cuma "perekat": gabungin semua mixin (data layer + tiap command)
jadi satu SpyCog, plus definisi group `xspy` itu sendiri. Command actualnya
ada di modul masing-masing:

  constants.py  — konstanta
  utils.py      — fungsi murni (formatting/klasifikasi)
  api.py        — data layer (WarEra API + Supabase), ApiMixin
  player.py     — `xspy player`, `xspy raw`, PlayerMixin
  mu.py         — `xspy mu`, MuMixin
  country.py    — `xspy country`, CountryMixin
  check.py      — `xspy check`, CheckMixin
  trade.py      — `xspy trade`, TradeMixin

Subcommand di-attach manual lewat `cmd_spy.add_command(...)` setelah class
SpyCog selesai dibuat (bukan @commands.command lepas) — supaya definisi
command tinggal di file masing-masing tanpa circular import.
"""

from __future__ import annotations

import logging

from discord.ext import commands

from .api import ApiMixin
from .player import PlayerMixin
from .mu import MuMixin
from .country import CountryMixin
from .check import CheckMixin
from .trade import TradeMixin
from .workers import WorkersMixin
from .wage import WageMixin
from .orders import OrdersMixin
from core.utils import make_embed

log = logging.getLogger("WarEraBot.spy")


class SpyCog(PlayerMixin, MuMixin, CountryMixin, CheckMixin, TradeMixin, WorkersMixin, WageMixin, OrdersMixin, ApiMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        # Attach subcommands here (per-instance), not at module/class level.
        # discord.py copies every Command in __cog_commands__ when the cog is
        # instantiated (Cog.__new__), to avoid shared state across reloads.
        # If subcommands are attached to the group at import time on the
        # *class* objects (SpyCog.spy_player, etc.), the copy/reparent step
        # can leave the copies' `.cog` unset -> TypeError: missing 'ctx'.
        # Using `self.xxx` here guarantees we attach the actual instance-bound
        # copies that will have `.cog` set correctly right after this runs.
        for _cmd in (
            self.spy_player,
            self.spy_raw,
            self.spy_mu,
            self.spy_country,
            self.spy_check,
            self.spy_trade,
            self.spy_scan_status,
            self.spy_workers,
            self.spy_wage,
            self.spy_order,
        ):
            if _cmd.name not in self.cmd_spy.all_commands:
                self.cmd_spy.add_command(_cmd)

        import market as mkt
        mkt.log_token_status()

        # Start background tasks
        # REAKTIVASI (Agustus 2026): company_index dipindah ke app_db, dan
        # 2 loop ini sekarang cuma melayani data agregat region/negara (xspy
        # country, web API halaman negara, estimasi pajak negara, xspy scan)
        # — BUKAN lagi demi akurasi xspy player (itu on-demand per user, lihat
        # market.fetch_and_cache_user_companies). Interval dinaikkan 3->12 jam
        # (lihat cogs/spy/constants.py) karena kebutuhan freshness data ini
        # jauh lebih longgar. cleanup_stale_task ikut auto lagi (pasangan
        # alami full-scan, bukan lagi manual).
        self.refresh_company_index.start()
        try:
            from .api.player_activity import PlayerActivityRunner
            self._player_activity = PlayerActivityRunner(self.bot)
            self._player_activity.start()
        except Exception as exc:
            log.error(f"PlayerActivityRunner gagal start: {exc!r}", exc_info=True)
        try:
            from .api.company_owner_refresh import CompanyOwnerRefreshRunner
            self._company_owner_refresh = CompanyOwnerRefreshRunner(self.bot)
            self._company_owner_refresh.start()
        except Exception as exc:
            log.error(f"CompanyOwnerRefreshRunner gagal start: {exc!r}", exc_info=True)
        self.cleanup_stale_task.start()
        self.full_stale_check_task.start()  # tiap 6 jam: verifikasi & hapus company is_full-stale (mati lebih cepat)
        self.refresh_daily_snapshots.start()  # xspy check v3: snapshot dmg/wealth harian — tidak berubah

        log.info("SpyCog loaded.")
        log.info(f"Spy subcommands: {[c.name for c in self.cmd_spy.commands]}")
        log.info(
            "Background tasks: refresh_company_index (12 jam + tahap prioritas item/region berubah), "
            "cleanup_stale_task (1x/hari 03:00 UTC), "
            "full_stale_check_task (6 jam, kandidat is_full-stale >3d), "
            "refresh_daily_snapshots (1x/hari 00:05 UTC / 07:05 WIB)"
        )

    async def cog_unload(self) -> None:
        # Batalkan semua task saat cog di-unload
        self.refresh_company_index.cancel()
        if getattr(self, "_player_activity", None):
            self._player_activity.stop()
        if getattr(self, "_company_owner_refresh", None):
            self._company_owner_refresh.stop()
        self.cleanup_stale_task.cancel()
        self.full_stale_check_task.cancel()
        self.refresh_daily_snapshots.cancel()

    @commands.group(name="spy", invoke_without_command=True, case_insensitive=True)
    async def cmd_spy(self, ctx: commands.Context) -> None:
        e = make_embed("🔍 Spy Commands")
        e.description = (
            "**`xspy player <n>`** — Player intel\n"
            "**`xspy mu <n>`** — Military Unit roster\n"
            "**`xspy country <n>`** — Country intel (ekonomi, company, militer, politik)\n"
            "**`xspy trade <n>`** — Win rate trading player (FIFO, seluruh histori)\n"
            "**`xspy raw <n>`** — [Admin] Dump raw JSON (buat riset/pengembangan)\n"
            "**`xspy check <n>`** — Growth harian: weekly/total dmg & total wealth vs kemarin\n"
            "**`xspy scan`** — [Admin] Lihat progress background scan company_index\n"
            "**`xspy workers <n>`** — [Admin] Worker pabrik player + pajak region\n"
            "**`xspy wage <n>`** — [Admin] Estimasi wage player\n"
            "**`xspy order <username> <item> [buy|sell]`** — Posisi player di antrian order book"
        )
        await ctx.send(embed=e)


# NOTE: subcommand attaching (spy_player, spy_raw, spy_mu, spy_country,
# spy_check, spy_trade -> children of cmd_spy) now happens in
# SpyCog.cog_load(), using instance attributes (self.spy_player, etc.)
# instead of class attributes. See cog_load() for why: discord.py copies
# every Command when the cog is instantiated, and attaching to the
# class-level objects here (before that copy happens) could leave the
# copies with .cog unset, causing
# "TypeError: ...spy_player() missing 1 required positional argument: 'ctx'"
# at runtime.


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SpyCog(bot))