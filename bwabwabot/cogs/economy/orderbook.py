"""
cogs/economy/orderbook.py  —  xorderbook <item>  (Full order book)
"""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

import market as mkt
from services import visuals as vis

from services.economy.formatters import _fmt_price
from core.formatters import fmt_compact
from .base import EconomyBase, _embed


def _summarize_orders(orders: list[dict]) -> tuple[int, int, int, int, int, int]:
    """Hitung unique user/MU/country + total qty per kategori."""
    users, mus, countries = set(), set(), set()
    qty_p, qty_m, qty_c = 0, 0, 0
    for o in orders:
        try:
            qty = max(0, int(float(o.get("quantity", 0) or 0)))
        except (TypeError, ValueError):
            qty = 0
        if o.get("mu"):
            mus.add(o["mu"])
            qty_m += qty
        elif o.get("country"):
            countries.add(o["country"])
            qty_c += qty
        else:
            if o.get("user"): users.add(o["user"])
            qty_p += qty
    return len(users), len(mus), len(countries), qty_p, qty_m, qty_c


class OrderbookCommands(EconomyBase):

    @commands.command(name="orderbook", aliases=["ob"])
    async def cmd_orderbook(self, ctx: commands.Context, *, item: str) -> None:
        async with ctx.typing():
            if self._session is None:
                await ctx.send("❌ Session not ready.")
                return
            ob = await mkt.fetch_orderbook(self._session, item)
        if ob is None:
            await ctx.send(f"❌ Failed to fetch Order Book for `{item}`.")
            return

        name, bids, asks = ob["item"], ob["bids"], ob["asks"]
        best_bid, best_ask, spread = ob["best_bid"], ob["best_ask"], ob["spread"]
        buy_vol, sell_vol = ob["buy_vol"], ob["sell_vol"]
        pressure = ("🟢 Buy pressure" if buy_vol > sell_vol * 1.2
                    else "🔴 Sell pressure" if sell_vol > buy_vol * 1.2
                    else "⚪ Balanced")

        e = _embed(f"📒 Order Book — {name}", discord.Color.dark_gold())
        header = []
        if best_bid is not None: header.append(f"**Bid:** `{_fmt_price(best_bid)}`")
        if best_ask is not None: header.append(f"**Ask:** `{_fmt_price(best_ask)}`")
        if spread   is not None: header.append(f"**Spread:** `{_fmt_price(spread)}`")
        if self._price_cache.get(name): header.append(f"**Price:** `{_fmt_price(self._price_cache[name])}`")
        e.description = "  |  ".join(header)
        e.add_field(name="Market Pressure", value=pressure, inline=True)
        if best_bid and best_ask:
            e.add_field(name="Mid Price", value=f"`{_fmt_price((best_bid+best_ask)/2)}`", inline=True)
        e.add_field(name="Volume", value=f"🟢 Buy: `{buy_vol:,}`  🔴 Sell: `{sell_vol:,}`", inline=False)
        b_u, b_m, b_c, b_qp, b_qm, b_qc = _summarize_orders(ob.get("raw_buys", []))
        s_u, s_m, s_c, s_qp, s_qm, s_qc = _summarize_orders(ob.get("raw_sells", []))
        summary_text = (
            "```\n"
            f"BID · USER TOTAL\n"
            f"PERSONAL   {b_u:>3} orang   {fmt_compact(b_qp):>6}\n"
            f"MU         {b_m:>3} MU      {fmt_compact(b_qm):>6}\n"
            f"COUNTRY    {b_c:>3} negara  {fmt_compact(b_qc):>6}\n\n"
            f"ASK · USER TOTAL\n"
            f"PERSONAL   {s_u:>3} orang   {fmt_compact(s_qp):>6}\n"
            f"MU         {s_m:>3} MU      {fmt_compact(s_qm):>6}\n"
            f"COUNTRY    {s_c:>3} negara  {fmt_compact(s_qc):>6}\n"
            "```"
        )
        e.add_field(name="Market Breakdown", value=summary_text, inline=False)
        e.add_field(name="ℹ️ Legend", value="`Depth`=cumulative • `Size`=qty • `Ord`=order count", inline=False)
        await ctx.send(embed=e)

        last_price = self._price_cache.get(name)
        pages = await asyncio.to_thread(vis.generate_orderbook_images, name, bids, asks, last_price=last_price)
        if pages:
            await ctx.send(files=pages)
        else:
            # Fallback ke teks kalau gagal render gambar (bot tetap jalan)
            def _parts(orders):
                rows = [
                    f"`#{i+1:02d}` `{_fmt_price(o['price'])}`  Qty: `{o['qty']:,}`"
                    + (f"  ({o['count']} orders)" if o.get("count", 1) > 1 else "")
                    + f"  Cum: `{o['cumQty']:,}`"
                    for i, o in enumerate(orders)
                ]
                chunk, parts = "", []
                for row in rows:
                    if len(chunk) + len(row) + 1 > 950:
                        parts.append(chunk); chunk = ""
                    chunk += row + "\n"
                if chunk:
                    parts.append(chunk)
                return parts

            for i, part in enumerate(_parts(bids)):
                e2 = _embed(f"🟢 BID ({len(bids)} levels — vol: {buy_vol:,})" if i == 0 else "🟢 BID (continued)", discord.Color.green())
                e2.description = part
                await ctx.send(embed=e2)

            for i, part in enumerate(_parts(asks)):
                e3 = _embed(f"🔴 ASK ({len(asks)} levels — vol: {sell_vol:,})" if i == 0 else "🔴 ASK (continued)", discord.Color.red())
                e3.description = part
                await ctx.send(embed=e3)
