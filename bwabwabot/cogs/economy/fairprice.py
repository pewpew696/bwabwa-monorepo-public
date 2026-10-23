"""cogs/economy/fairprice.py — xfairprice [item] (alias: xfp)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

import market as mkt
from services.economy.formatters import _fmt_price, _fmt_pct
from services.economy.db_history import get_price_history
from services.economy.fairprice_display import (
    ITEM_SHORT_NAMES, NAME_COL_WIDTH, _short_name,
)
from services.economy.fairprice_market import (
    _fp_spread_pct, _fp_spread_label, fp_parse_orderbook,
)
from services.economy.fairprice_reason import (
    _fp_reason_key, fp_compute_reasons,
)
from services.economy.fairprice_cost import fp_compute_cost_engine
from services.economy.fairprice_engine import (
    fp_compute_confidence, fp_compute_fair_range, fp_compute_risk,
    fp_compute_technical_value, fp_compute_valuation, fp_decide_recommendation,
)
from services.economy.fairprice_liquidity import (
    fp_compute_data_confidence, fp_compute_liquidity_view,
)
from .base import ANCHOR_MAX_AGE_DAYS, EconomyBase, _embed, ITEM_EMOJI, PRODUCTION_CHAIN

log = logging.getLogger(__name__)

# --- constants / thresholds ---

from services.economy.constants import CONFIDENCE_GATE

class FairPriceCommands(EconomyBase):

    # --- market helpers ---

    async def _fp_trend_30d(self, item: str) -> tuple[str, str]:
        rows = await get_price_history(item, hours=720)
        if len(rows) < 2:
            return "⚪ Sideways (insufficient 30d data)", "Sideways"

        baseline = rows[0]["price"]
        current  = rows[-1]["price"]
        if not baseline:
            return "⚪ Sideways (insufficient 30d data)", "Sideways"

        chg = (current - baseline) / baseline * 100
        if chg > 3.0:
            return f"🟢 Bullish (30d {chg:+.1f}%)", "Bullish"
        if chg < -3.0:
            return f"🔴 Bearish (30d {chg:+.1f}%)", "Bearish"
        return f"⚪ Sideways (30d {chg:+.1f}%)", "Sideways"

    # --- valuation engine ---

    async def _fp_analyze(self, item: str, orderbook) -> Optional[dict]:
        """orderbook: dict | None | sentinel "error" (fetch gagal)."""
        current_price = self._price_cache.get(item)
        if current_price is None:
            return None
        is_producible = item in PRODUCTION_CHAIN

        orderbook_failed = isinstance(orderbook, str)
        if orderbook_failed:
            orderbook = None

        cost = fp_compute_cost_engine(
            self._price_cache, item, is_producible,
            self._get_median_bonus, self._get_bonus,
        )
        if cost is None:
            return None
        pp_value        = cost["pp_value"]
        cost_info       = cost["cost_info"]
        bonus_best_pct  = cost["bonus_best_pct"]
        production_cost = cost["production_cost"]
        break_even      = cost["break_even"]

        ob = fp_parse_orderbook(orderbook)
        best_bid     = ob["best_bid"]
        best_ask     = ob["best_ask"]
        buy_vol      = ob["buy_vol"]
        sell_vol     = ob["sell_vol"]
        total_qty    = ob["total_qty"]
        spread_pct   = ob["spread_pct"]
        spread_label = ob["spread_label"]
        spread_key   = ob["spread_key"]

        liq_data = self._liquidity_score_cache.get(item) if is_producible else None
        liq_view = fp_compute_liquidity_view(liq_data, is_producible)
        if liq_view is None:
            return None
        weight_tech     = liq_view["weight_tech"]
        weight_intr     = liq_view["weight_intr"]
        margin_pct      = liq_view["margin_pct"]
        liq_score       = liq_view["liq_score"]
        liq_key         = liq_view["liq_key"]
        liquidity_label = liq_view["liquidity_label"]

        intrinsic_value = production_cost if is_producible else 0.0

        history = self._price_history.get(item, [])
        tv = fp_compute_technical_value(
            history, current_price, is_producible, datetime.now(timezone.utc),
        )
        if tv is None:
            return None
        technical_value = tv["technical_value"]

        fr = fp_compute_fair_range(
            technical_value, intrinsic_value, weight_tech, weight_intr,
            margin_pct, is_producible, production_cost, best_bid,
        )
        fair_value = fr["fair_value"]
        fair_price = fr["fair_price"]
        fair_lower = fr["fair_lower"]
        fair_upper = fr["fair_upper"]
        good_buy   = fr["good_buy"]
        good_sell  = fr["good_sell"]

        val = fp_compute_valuation(
            current_price, fair_price, fair_lower, fair_upper, fair_value,
        )
        valuation_pct = val["valuation_pct"]
        valuation_key = val["valuation_key"]
        expected_edge = val["expected_edge"]

        trend_label, trend_key = await self._fp_trend_30d(item)

        conf = fp_compute_confidence(
            spread_key, len(history), best_bid is not None, best_ask is not None,
            is_producible, cost_info, pp_value,
        )
        effective_conf = conf["effective_conf"]

        trend_opposes = (
            (valuation_key == "Undervalued" and trend_key == "Bearish") or
            (valuation_key == "Overvalued" and trend_key == "Bullish")
        )
        risk_label = fp_compute_risk(
            spread_key, is_producible, liq_score, effective_conf, trend_opposes,
        )

        low_confidence = effective_conf < CONFIDENCE_GATE
        recommendation = fp_decide_recommendation(
            low_confidence, current_price, good_buy, good_sell,
        )

        reason_key = _fp_reason_key(recommendation, valuation_key, low_confidence)
        reasons = fp_compute_reasons(
            reason_key, valuation_key, valuation_pct, spread_key,
            is_producible, liq_key, liq_score, orderbook_failed,
            trend_opposes, trend_key,
        )

        anchor_age = self._liquidity_anchor_meta.get("anchor_age_days")
        data_confidence = fp_compute_data_confidence(liq_data, is_producible, anchor_age)

        pe = self._price_extremes_cache.get(item)
        price_extremes = dict(pe) if pe else None

        return {
            "item": item,
            "current_price": current_price,
            "production_cost": production_cost,
            "break_even": break_even,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": spread_pct,
            "spread_label": spread_label,
            "liquidity_label": liquidity_label,
            "liquidity_score": liq_score,
            "weight_tech": weight_tech,
            "weight_intr": weight_intr,
            "total_qty": total_qty,
            "margin_pct": margin_pct,
            "fair_value": fair_value,
            "fair_price": fair_price,
            "fair_lower": fair_lower,
            "fair_upper": fair_upper,
            "good_buy": good_buy,
            "good_sell": good_sell,
            "valuation_key": valuation_key,
            "valuation_pct": valuation_pct,
            "expected_edge": expected_edge,
            "trend_label": trend_label,
            "trend_key": trend_key,
            "risk_label": risk_label,
            "recommendation": recommendation,
            "reason_key": reason_key,
            "reasons": reasons,
            "data_confidence": data_confidence,
            "price_extremes": price_extremes,
            "bonus_median_pct": cost_info["bonus_pct"] if is_producible else None,
            "bonus_median_source": cost_info["bonus_source"] if is_producible else "not_applicable",
            "bonus_best_pct": bonus_best_pct,
        }

    # --- embed builder (detail, 1 item) ---

    def _fp_build_embed(self, a: dict) -> discord.Embed:
        item = a["item"]
        rec_color = {
            "BUY":  discord.Color.green(),
            "SELL": discord.Color.red(),
            "HOLD": discord.Color.gold(),
        }[a["recommendation"]]

        e = _embed(f"📦 {ITEM_EMOJI.get(item, '📦')} {item} — Fair Price Analysis", rec_color)

        val_emoji = {"Undervalued": "🟢", "Overvalued": "🔴", "Fair": "⚪"}[a["valuation_key"]]
        val_text = (
            f"{val_emoji} {a['valuation_key']}"
            + (f" ({a['valuation_pct']:+.1f}%)" if a["valuation_key"] != "Fair" else "")
        )

        e.add_field(name="Current Price", value=f"`{_fmt_price(a['current_price'])}`", inline=True)
        e.add_field(
            name="Fair Range",
            value=f"`{_fmt_price(a['fair_lower'])} – {_fmt_price(a['fair_upper'])}`",
            inline=True,
        )
        e.add_field(name="Valuation", value=val_text, inline=True)
        e.add_field(name="Expected Edge", value=f"**{a['expected_edge']:+.1f}%**", inline=True)

        rec_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}[a["recommendation"]]
        e.add_field(name="Recommendation", value=f"{rec_emoji} **{a['recommendation']}**", inline=True)
        e.add_field(name="Risk", value=a["risk_label"], inline=True)

        be_str   = _fmt_price(a["break_even"]) if a["break_even"] is not None else "N/A (non-producible)"
        cost_str = _fmt_price(a["production_cost"]) if a["production_cost"] is not None else "N/A (non-producible)"
        val_lines = [
            f"Break Even      `{be_str}`",
            f"Production Cost `{cost_str}`",
            f"Good Buy        `< {_fmt_price(a['good_buy'])}`",
            f"Good Sell       `> {_fmt_price(a['good_sell'])}`",
        ]
        if a["bonus_median_source"] == "not_applicable":
            val_lines.append("📉 Bonus not applicable (non-producible item)")
        elif a["bonus_median_source"] == "none":
            val_lines.append("📉 Bonus (median) not available yet — fallback 0%")
        else:
            val_lines.append(f"📉 Bonus used (median) `{a['bonus_median_pct']:.1f}%`")
        if a["bonus_best_pct"] is not None:
            val_lines.append(f"📈 Best bonus (max, not used) `{a['bonus_best_pct']:.1f}%`")
        pe = a.get("price_extremes")
        if pe:
            val_lines.append(
                f"📊 Recorded range since {pe['tracked_since']}: "
                f"`{_fmt_price(pe['recorded_low'])} – {_fmt_price(pe['recorded_high'])}`"
            )
        e.add_field(
            name="─── VALUATION ───",
            value="\n".join(val_lines),
            inline=False,
        )

        best_bid_s = _fmt_price(a["best_bid"]) if a["best_bid"] is not None else "—"
        best_ask_s = _fmt_price(a["best_ask"]) if a["best_ask"] is not None else "—"
        spread_s   = f"{a['spread_pct']:.1f}%" if a["spread_pct"] is not None else "—"
        liq_s = f"(score {a['liquidity_score']:.2f})" if a["liquidity_score"] is not None else "(non-producible)"
        e.add_field(
            name="─── MARKET ───",
            value=(
                f"Best Bid   `{best_bid_s}`\n"
                f"Best Ask   `{best_ask_s}`\n"
                f"Spread     {a['spread_label']} ({spread_s})\n"
                f"Liquidity  {a['liquidity_label']} {liq_s}\n"
                f"Order Book {a['total_qty']} units available\n"
                f"Trend (30d) {a['trend_label']}"
            ),
            inline=False,
        )

        dc = a.get("data_confidence") or {}
        dc_notes: list[str] = []
        if dc.get("liquidity_basis") == "provisional":
            dc_notes.append(f"⚠️ Liquidity score is provisional ({dc.get('liquidity_history_days')} days of data)")
        anchor_age = dc.get("anchor_age_days")
        if anchor_age is not None and anchor_age > ANCHOR_MAX_AGE_DAYS:
            dc_notes.append(f"⚠️ Calibration anchor is {anchor_age} days old")
        raw = dc.get("raw_liquidity_score")
        if raw is not None and (raw > 1.0 or raw < 0.0):
            dc_notes.append(f"⚠️ Liquidity score outside calibration range (raw {raw:+.2f})")
        if dc_notes:
            e.add_field(name="Data Confidence", value="\n".join(dc_notes), inline=False)

        e.add_field(name="Reason", value="\n".join(f"• {r}" for r in a["reasons"]), inline=False)
        return e

    # --- commands ---

    @commands.command(name="fairprice", aliases=["fp"])
    async def cmd_fairprice(self, ctx: commands.Context, *, item: Optional[str] = None) -> None:
        if not self._price_cache:
            await ctx.send("⏳ Data not ready yet.")
            return
        if self._session is None:
            await ctx.send("❌ Session not ready.")
            return

        if item:
            name = self._resolve(item)
            if name is None or self._price_cache.get(name) is None:
                await ctx.send(f"⚠️ Item `{item}` not found.")
                return
            async with ctx.typing():
                await self._ensure_daily_caches()
                try:
                    orderbook = await mkt.fetch_orderbook(self._session, name)
                except Exception as exc:
                    log.warning(f"fetch_orderbook({name}) gagal: {exc}")
                    await ctx.send(f"⚠️ Failed to fetch orderbook data for `{name}`, try again.")
                    return
                analysis = await self._fp_analyze(name, orderbook)
            if analysis is None:
                await ctx.send(f"⚠️ Price data for `{name}`'s inputs isn't complete yet — try `xrefresh` first.")
                return
            await ctx.send(embed=self._fp_build_embed(analysis))
            return

        await self._fp_send_list(ctx)

    async def _fp_send_list(self, ctx: commands.Context) -> None:
        candidates = list(self._price_cache.keys())

        async with ctx.typing():
            results = await self._fp_analyze_batch(self._session, candidates)

        if not results:
            await ctx.send("⚠️ Not enough data yet to calculate fair price. Try `xrefresh` first.")
            return

        results.sort(key=lambda a: a["expected_edge"], reverse=True)

        buy_n  = sum(1 for a in results if a["recommendation"] == "BUY")
        sell_n = sum(1 for a in results if a["recommendation"] == "SELL")
        hold_n = len(results) - buy_n - sell_n
        summary = f"🟢 {buy_n} BUY   🔴 {sell_n} SELL   ⚪ {hold_n} HOLD"

        pages = self._fp_build_list_pages(results, summary)

        view = FairPriceListView(pages, ctx.author.id) if len(pages) > 1 else None
        await ctx.send(embed=pages[0], view=view)

    def _fp_build_list_pages(self, results: list[dict], summary: str) -> list[discord.Embed]:
        sig_map = {"BUY": "🟢 BUY ", "SELL": "🔴 SELL", "HOLD": "⚪ HOLD"}
        HDR = f"{'Item':<{NAME_COL_WIDTH}}{'Current':>9}{'Fair':>9}  {'Signal':<7}{'Edge':>8}\n"
        DIV = f"{'─'*NAME_COL_WIDTH}{'─'*9}{'─'*9}  {'─'*7}{'─'*8}\n"

        rows = [
            f"{_short_name(a['item']):<{NAME_COL_WIDTH}}"
            f"{_fmt_price(a['current_price']):>9}"
            f"{_fmt_price(a['fair_price']):>9}  "
            f"{sig_map[a['recommendation']]:<7}"
            f"{a['expected_edge']:+6.1f}%"
            for a in results
        ]

        MAX_CHARS_PER_PAGE = 1800
        chunk_lines: list[str] = []
        chunks: list[str] = []
        char_count = len(HDR) + len(DIV)
        for row in rows:
            if char_count + len(row) + 1 > MAX_CHARS_PER_PAGE and chunk_lines:
                chunks.append(HDR + DIV + "\n".join(chunk_lines))
                chunk_lines, char_count = [], len(HDR) + len(DIV)
            chunk_lines.append(row)
            char_count += len(row) + 1
        if chunk_lines:
            chunks.append(HDR + DIV + "\n".join(chunk_lines))

        total = len(chunks)
        pages: list[discord.Embed] = []
        for i, part in enumerate(chunks, start=1):
            e = _embed("🏪 Fair Price — All Items", discord.Color.teal())
            e.description = f"```\n{part}\n```"
            footer_bits = [summary]
            if total > 1:
                footer_bits.append(f"Page {i}/{total}")
            e.set_footer(text="  •  ".join(footer_bits))
            pages.append(e)
        return pages


class FairPriceListView(discord.ui.View):
    """Navigasi 1 pesan buat list xfp."""
    def __init__(self, pages: list[discord.Embed], author_id: int):
        super().__init__(timeout=120)
        self.pages    = pages
        self.author_id = author_id
        self.index    = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran this command can navigate.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = (self.index - 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = (self.index + 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)
