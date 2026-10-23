"""
cogs/economy/item.py  —  xitem [name]  (Price + production bonus)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

from services.economy.formatters import _fmt_price, _fmt_pct, _format_duration, _format_remaining
from .base import EconomyBase, _embed, ITEM_EMOJI, ITEM_NOT_PRODUCIBLE


class ItemCommands(EconomyBase):

    @commands.command(name="item", aliases=["i"])
    async def cmd_item(self, ctx: commands.Context, *, item: Optional[str] = None) -> None:
        if not self._price_cache:
            await ctx.send("⏳ Data not ready yet.")
            return

        if item:
            name = self._resolve(item)
            if name is None:
                await ctx.send(f"Item `{item}` not found.")
                return
            price      = self._price_cache[name]
            pct, source = self._get_bonus(name)
            e = _embed(f"📦 {ITEM_EMOJI.get(name, '📦')} {name}", discord.Color.gold())
            e.add_field(name="Price", value=f"`{_fmt_price(price)}`", inline=True)
            if source == "manual":
                override = next(v for k, v in self._manual_overrides.items() if k.lower() == name.lower())
                e.add_field(name="Production Bonus", value=f"**+{_fmt_pct(pct)}%**  🔧 manual", inline=True)
                e.add_field(name="Override expires", value=_format_remaining(override["expires_at"]), inline=False)
            elif source == "auto":
                e.add_field(name="Production Bonus", value=f"**+{_fmt_pct(pct)}%**  🌐 auto", inline=True)
            else:
                e.add_field(name="Production Bonus", value="0%", inline=True)

            top_countries = self._bonus_breakdown.get(name, [])
            deposit_ends = self._bonus_deposit_ends.get(name, {})
            now_utc = datetime.now(timezone.utc)
            # deposit yang masa berlakunya sudah lewat langsung dibuang dari tampilan —
            # snapshot breakdown cuma dihitung ulang tiap 60 menit, jadi bisa basi.
            live = [
                (c, p) for c, p in top_countries
                if not (c in deposit_ends and deposit_ends[c] <= now_utc)
            ]
            expired_hidden = len(top_countries) - len(live)
            if live:
                medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                lines = []
                for i, (country, bonus_pct) in enumerate(live):
                    medal = medals[i] if i < len(medals) else f"#{i+1}"
                    line = f"{medal} **{country}** — +{_fmt_pct(bonus_pct)}%"
                    if country in deposit_ends:
                        line += f"  ⏳ {_format_duration(deposit_ends[country])}"
                    income_tax = self._country_tax_cache.get(country)
                    if income_tax is not None:
                        line += f"  (tax {_fmt_pct(income_tax)}%)"
                    lines.append(line)
                e.add_field(name="🌍 Top Production Bonus", value="\n".join(lines), inline=False)
                notes = []
                if any(c in deposit_ends for c, _ in live):
                    notes.append("⏳ = time left on the deposit bonus (it drops after that).")
                if expired_hidden:
                    notes.append(f"{expired_hidden} ended deposit(s) hidden.")
                if notes:
                    notes.append("List refreshes hourly — `xrefresh` updates it now.")
                    e.add_field(name="ℹ️ Note", value=" ".join(notes), inline=False)
            elif top_countries:
                e.add_field(
                    name="🌍 Top Production Bonus",
                    value="_All listed deposit bonuses have just ended — the list refreshes hourly (`xrefresh` updates it now)._",
                    inline=False,
                )
            else:
                e.add_field(
                    name="🌍 Top Production Bonus",
                    value="_No data yet — run `xrefresh` first._",
                    inline=False,
                )

            e.add_field(name="Trend (60m)", value=self._trend(name, price), inline=False)
            await ctx.send(embed=e)
            return

        self._cleanup_overrides()
        visible = {k: v for k, v in self._price_cache.items() if k not in ITEM_NOT_PRODUCIBLE}
        HDR  = f"{'Item':<16}{'Price':>9}{'Bonus':>9}\n"
        DIV  = f"{'─'*16}{'─'*9}{'─'*9}\n"
        rows = []
        for name, price in sorted(visible.items()):
            pct, source = self._get_bonus(name)
            if pct > 0:
                tag = f"+{pct:.1f}%{'M' if source == 'manual' else 'A'}"
            else:
                tag = "—"
            rows.append(f"{name[:16]:<16}{_fmt_price(price):>9}{tag:>9}")

        chunk_lines, parts, char_count = [], [], len(HDR) + len(DIV)
        for row in rows:
            if char_count + len(row) + 1 > 1700:
                parts.append(HDR + DIV + "\n".join(chunk_lines))
                chunk_lines, char_count = [], len(HDR) + len(DIV)
            chunk_lines.append(row)
            char_count += len(row) + 1
        if chunk_lines:
            parts.append(HDR + DIV + "\n".join(chunk_lines))

        for i, part in enumerate(parts):
            e = _embed(f"🏪 All Items {'(continued)' if i else f'({len(visible)} items)'}", discord.Color.teal())
            e.description = f"```\n{part}\n```"
            if i == 0:
                e.set_footer(text="A = auto-fetch  M = manual override (1h)  •  bwabwabwa")
            await ctx.send(embed=e)
