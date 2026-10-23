"""
cogs/spy/trade.py — `xspy trade`.

TradeMixin butuh ApiMixin (self._search_user_ids, self._get_user_lite,
self._fetch_trade_winrate, self._session). Command didefinisikan lepas
(@commands.command) lalu disambungkan ke group `xspy` secara manual di
__init__.py — sama persis pola CountryMixin di country.py.

Publik: bisa dipakai buat cek winrate SIAPA AJA, tidak ada guard/permission
khusus (keputusan user).
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands
from core.blocklist import is_player_blocked
from core.permissions import get_level, LEVEL_BOT_ADMIN
from core.messages import MSG_BLOCKED_SPY

from core.utils import make_embed
from services.spy.utils import fmt_k, not_found_msg
from services.spy.trade import fetch_trade_winrate
from services.spy.search import find_player_exact

log = logging.getLogger("WarEraBot.spy")


class TradeMixin:
    """Mixin — expects ApiMixin di final class."""

    @commands.command(name="trade", aliases=["wr", "winrate"])
    async def spy_trade(self, ctx: commands.Context, *, nama: str) -> None:
        """Win rate trading player (FIFO, seluruh histori). Example: xspy trade SaguKeju

        CATATAN AKURASI: FIFO matching cuma bisa jalan kalau BELI dan JUAL
        item yang sama sama-sama ke-capture dalam histori yang berhasil
        di-fetch. Kalau item didapat dari produksi/gift/company (bukan
        beli di market), penjualannya tidak akan match cost basis apapun
        dan otomatis di-skip dari itungan Closed Trades — bukan dihitung
        sebagai loss, tapi memang tidak dihitung sama sekali.

        PARAMETER HARI (opsional): `xspy trade SaguKeju 30` (atau `30d`) = hanya
        transaksi 30 hari terakhir yang dihitung. Tanpa angka = seluruh histori.
        Beli di luar rentang lalu jual di dalam rentang tidak masuk Closed Trades.
        """
        # Hari opsional di ujung: "nama 30" / "nama 30d". Angka cuma dianggap
        # hari kalau berdiri sendiri sebagai kata terakhir & masih ada nama di depannya.
        days_back = None
        _parts = nama.rsplit(None, 1)
        if len(_parts) == 2:
            _tok = _parts[1].lower()
            if _tok.endswith("d"):
                _tok = _tok[:-1]
            if _tok.isdigit():
                nama = _parts[0].strip()
                _n = int(_tok)
                days_back = min(_n, 36500) if _n > 0 else None
        period_note = f" in the last {days_back} days" if days_back else ""
        title_suffix = f" ({days_back}d)" if days_back else ""
        async with ctx.typing():
            user_data, suggestions = await find_player_exact(self._session, nama)
            if not user_data:
                await ctx.send(f"⚠️ {not_found_msg('Player', nama, suggestions, md=True)}")
                return
            user_id = user_data["_id"]
            if await is_player_blocked(user_id):
                if await get_level(ctx.author) < LEVEL_BOT_ADMIN:
                    await ctx.send(MSG_BLOCKED_SPY)
                    return

            username = user_data.get("username", nama)

            result = await fetch_trade_winrate(self._session, user_id, days=days_back)

        if result["closed_trades"] == 0:
            await ctx.send(
                f"ℹ️ `{username}` has no closed trades that can be FIFO-matched "
                f"(may never have sold an item previously bought on the market, "
                f"or never traded at all){period_note}."
            )
            return

        e = make_embed(f"📊 Trading Win Rate: {username}{title_suffix}", discord.Color.gold())

        win_rate = result["win_rate"]
        profit = result["net_profit"]
        profit_str = f"+{fmt_k(profit)}" if profit >= 0 else f"-{fmt_k(abs(profit))}"
        profit_color_emoji = "🟢" if profit >= 0 else "🔴"

        e.add_field(
            name="🏆 Win Rate",
            value=f"`{win_rate:.1f}%` ({result['wins']}W / {result['losses']}L)",
            inline=True,
        )
        e.add_field(
            name=f"{profit_color_emoji} Net Profit",
            value=f"`{profit_str}g`",
            inline=True,
        )
        e.add_field(
            name="🔄 Closed Trades",
            value=f"`{result['closed_trades']}`",
            inline=True,
        )

        e.add_field(
            name="📦 Total Volume",
            value=(
                f"Buy: `{fmt_k(result['total_buy_qty'])}` item\n"
                f"Sell: `{fmt_k(result['total_sell_qty'])}` item\n"
                f"Total: `{fmt_k(result['total_volume'])}` item"
            ),
            inline=True,
        )

        best = result["best_item"]
        worst = result["worst_item"]
        item_val = (
            f"🥇 {best[0]}: `+{fmt_k(best[1])}g`\n" if best else "🥇 —\n"
        ) + (
            f"📉 {worst[0]}: `{fmt_k(worst[1])}g`" if worst else "📉 —"
        )
        e.add_field(name="Most Profitable/Losing Item", value=item_val, inline=True)

        first_dt = result["first_trade_at"]
        last_dt = result["last_trade_at"]
        date_val = (
            f"First: `{first_dt.strftime('%d %b %Y') if first_dt else '—'}`\n"
            f"Last: `{last_dt.strftime('%d %b %Y') if last_dt else '—'}`\n"
            f"Active Duration: `{result['active_days']}` days"
        )
        e.add_field(name="📅 Trading Range", value=date_val, inline=True)

        footer_note = f"Scanned {result['pages_fetched']} transaction pages"
        if result["capped"]:
            footer_note += " (capped by TX_MAX_PAGES — history may be incomplete)"
        e.set_footer(text=f"{footer_note}  •  bwabwabwa")

        await ctx.send(embed=e)
