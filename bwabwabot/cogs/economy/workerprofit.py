"""
cogs/economy/workerprofit.py  —  workerprofit (alias wp)

Analisa item paling profitable buat hire pekerja, dari sudut pandang employer
(worker cost side) — BUKAN pengganti profit.py (itu sudut pandang produksi,
PP-based per AE).

Formula dasar (rekonstruksi layer "Edit Worker > Estimated benefit" di game):
  Resource : base_net  = sell_price - wage_cost
             net_final = base_net + sell_price*(bonus_pct/100)
                         + sell_price*(fidelity_pct/100)
  Crafted  : raw_cost  = raw_price * raw_qty
             base_net  = sell_price - wage_cost - raw_cost
             net_final = base_net + raw_cost*(bonus_pct/100)
                         + raw_cost*(fidelity_pct/100)

Dua halaman (satu wage, tombol pindah halaman):
  Hal 1 Gross     — wage dipakai GROSS flat, sama untuk semua item.
  Hal 2 After Tax — wage jadi TARGET NET; gross_rate = wage / (1 - tax_pct/100).
                    Ranking dihitung ulang: gross efektif beda per item
                    (tax beda per negara top-producer item tsb).
Item tanpa data tax -> fallback 0%, ditandai `*` + disclaimer di footer.

Catatan:
  - bonus_pct (produksi) dan tax_pct (income) dua hal independen.
  - Fidelity SELALU masuk net_final, tidak pernah jadi baris terpisah.
  - Tax di-fetch on-demand via mkt.fetch_country_tax_breakdown.
"""

from __future__ import annotations

import discord
from discord.ext import commands

import market as mkt
from services.economy.formatters import _fmt_price, _fmt_pct
from .base import EconomyBase, _embed, PRODUCTION_CHAIN, ITEM_EMOJI
from .views import WorkerProfitPaginationView

WAGE_RATE_DEFAULT: float = 0.165
FIDELITY_PCT_DEFAULT: float = 10.0


class WorkerProfitCommands(EconomyBase):

    def _calc_net_final(
        self, sell_price: float, wage_cost: float, chain: dict, bonus_pct: float, fidelity: float,
    ) -> tuple[float, float | None] | None:
        """Formula bersama gross & after-tax: resource vs crafted, base_net -> net_bonus ->
        net_final. Return None kalau raw material item tsb tidak ada harga (caller skip item)."""
        if chain["input"] is None:
            base_net = sell_price - wage_cost
            net_bonus = base_net + sell_price * (bonus_pct / 100)
            net_final = net_bonus + sell_price * (fidelity / 100)
            return net_final, None

        input_name, input_qty = chain["input"]
        raw_price = self._price_cache.get(input_name)
        if raw_price is None:
            return None
        raw_cost = raw_price * input_qty
        base_net = sell_price - wage_cost - raw_cost
        net_bonus = base_net + raw_cost * (bonus_pct / 100)
        net_final = net_bonus + raw_cost * (fidelity / 100)
        return net_final, raw_cost

    def _build_gross_rows(self, wage: float, fidelity: float) -> list[tuple]:
        rows = []
        for name, chain in PRODUCTION_CHAIN.items():
            sell_price = self._price_cache.get(name)
            if sell_price is None:
                continue

            bonus_pct, source = self._get_bonus(name)
            pp = chain["pp"]
            wage_cost = wage * pp

            calc = self._calc_net_final(sell_price, wage_cost, chain, bonus_pct, fidelity)
            if calc is None:
                continue
            net_final, raw_cost = calc
            pp = chain["pp"]
            if pp <= 0:
                continue
            net_final = net_final / pp
            sell_price = sell_price / pp
            wage_cost = wage_cost / pp
            raw_cost = raw_cost / pp if raw_cost is not None else None

            rows.append((
                net_final, name, sell_price, wage_cost, raw_cost,
                bonus_pct, "🔧" if source == "manual" else "🌐",
                ITEM_EMOJI.get(name, "•"),
            ))
        rows.sort(key=lambda r: r[0], reverse=True)
        return rows[:10]

    def _build_tax_rows(self, net_wage: float, fidelity: float) -> tuple[list[tuple], bool]:
        rows = []
        any_fallback = False
        for name, chain in PRODUCTION_CHAIN.items():
            sell_price = self._price_cache.get(name)
            if sell_price is None:
                continue

            bonus_pct, source = self._get_bonus(name)
            pp = chain["pp"]

            breakdown = self._bonus_breakdown.get(name, [])
            top_country = breakdown[0][0] if breakdown else None
            tax_pct = self._country_tax_cache.get(top_country) if top_country else None
            fallback = tax_pct is None
            if fallback:
                tax_pct = 0.0
                any_fallback = True
            if tax_pct >= 100:
                continue

            gross_rate = net_wage / (1 - tax_pct / 100)
            wage_cost = gross_rate * pp

            calc = self._calc_net_final(sell_price, wage_cost, chain, bonus_pct, fidelity)
            if calc is None:
                continue
            net_final, raw_cost = calc
            pp = chain["pp"]
            if pp <= 0:
                continue
            net_final = net_final / pp
            sell_price = sell_price / pp
            wage_cost = wage_cost / pp
            raw_cost = raw_cost / pp if raw_cost is not None else None

            rows.append((
                net_final, name, sell_price, wage_cost, raw_cost,
                bonus_pct, "🔧" if source == "manual" else "🌐",
                ITEM_EMOJI.get(name, "•"),
                tax_pct, top_country or "N/A", fallback,
            ))
        rows.sort(key=lambda r: r[0], reverse=True)
        return rows[:10], any_fallback

    def _render_gross_lines(self, rows: list[tuple]) -> str:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for rank, (net_final, name, sell_price, wage_cost, raw_cost, bonus_pct, tag, emoji) in enumerate(rows, 1):
            sign = "+" if net_final >= 0 else ""
            lines.append(
                f"{medals.get(rank, f'#{rank:02d}')} {emoji} **{name}** {tag} (+{_fmt_pct(bonus_pct)}%)\n"
                f"   💰 Net: **{sign}{_fmt_price(net_final)}/pp** | Sell: {_fmt_price(sell_price)}/pp | "
                f"Wage: -{_fmt_price(wage_cost)}/pp"
                + (f" | Raw: -{_fmt_price(raw_cost)}/pp" if raw_cost is not None else "")
            )
        return "\n".join(lines)

    def _render_tax_lines(self, rows: list[tuple]) -> str:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for rank, (net_final, name, sell_price, wage_cost, raw_cost, bonus_pct, tag, emoji, tax_pct, country, fallback) in enumerate(rows, 1):
            sign = "+" if net_final >= 0 else ""
            star = "*" if fallback else ""
            lines.append(
                f"{medals.get(rank, f'#{rank:02d}')} {emoji} **{name}** {tag} (+{_fmt_pct(bonus_pct)}%)\n"
                f"   💰 Net: **{sign}{_fmt_price(net_final)}/pp** | Sell: {_fmt_price(sell_price)}/pp | "
                f"Wage: -{_fmt_price(wage_cost)}/pp (gross, tax {_fmt_pct(tax_pct)}% — {country}{star})"
                + (f" | Raw: -{_fmt_price(raw_cost)}/pp" if raw_cost is not None else "")
            )
        return "\n".join(lines)

    @commands.command(name="workerprofit", aliases=["wp"])
    async def cmd_workerprofit(
        self,
        ctx: commands.Context,
        wage: float = WAGE_RATE_DEFAULT,
        fidelity: float = FIDELITY_PCT_DEFAULT,
    ) -> None:
        if wage <= 0:
            await ctx.send("⚠️ Wage must be greater than 0.")
            return
        if not (0 <= fidelity <= 100):
            await ctx.send("⚠️ Fidelity must be between 0 and 100.")
            return
        if not self._price_cache:
            await ctx.send("⏳ Data not ready yet.")
            return

        async with ctx.typing():
            try:
                tax_map = await mkt.fetch_country_tax_breakdown(
                    self._session, self._bonus_breakdown, with_cache=True
                )
                if tax_map:
                    self._country_tax_cache.update(tax_map)
            except Exception:
                pass

            gross_rows = self._build_gross_rows(wage, fidelity)
            tax_rows, any_fallback = self._build_tax_rows(wage, fidelity)

            wage_label = f"{wage} (custom)" if wage != WAGE_RATE_DEFAULT else f"{WAGE_RATE_DEFAULT} (default, worst-case)"
            fidelity_label = f"{fidelity:.0f}% (custom)" if fidelity != FIDELITY_PCT_DEFAULT else f"{FIDELITY_PCT_DEFAULT:.0f}% (default)"

            e_gross = _embed("👷 Top Worker Profit — Gross", discord.Color.dark_gold())
            e_gross.description = self._render_gross_lines(gross_rows) or "⚠️ No data available."
            e_gross.set_footer(
                text=(
                    f"Wage: {wage_label} per pp (gross, flat for all items). "
                    f"Net includes fidelity bonus {fidelity_label} (not shown separately). "
                    "🌐 = auto bonus   🔧 = manual override"
                )
            )

            e_tax = _embed("👷 Top Worker Profit — After Tax", discord.Color.green())
            e_tax.description = self._render_tax_lines(tax_rows) or "⚠️ No data available."
            footer_tax = (
                f"Wage: {wage} (target NET take-home, per pp). Gross recalculated per item using "
                f"that item's top production-bonus country's income tax. "
                f"Net includes fidelity bonus {fidelity_label} (not shown separately). "
                "🌐 = auto bonus   🔧 = manual override"
            )
            if any_fallback:
                footer_tax += "  •  * = tax data unavailable, assumed 0% (gross = net as-is)"
            e_tax.set_footer(text=footer_tax)

            if not gross_rows and not tax_rows:
                await ctx.send("⚠️ No data available for any producible item right now.")
                return

            view = WorkerProfitPaginationView(e_gross, e_tax)
            view.message = await ctx.send(embed=e_gross, view=view)
