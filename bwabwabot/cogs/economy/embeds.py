"""
cogs/economy/embeds.py  —  Fungsi pembangun discord.Embed & tabel teks
yang dipakai bersama oleh views.py dan berbagai cmd_*.py.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

import discord

import market as mkt

from services.economy.formatters import _fmt_price, _fmt_pct, _fmt_money, _fmt_compact
from .base import _embed


# --- market (spread / volume) ---

def build_spread_embed(spreads: list[dict]) -> discord.Embed:
    HDR  = f"{'Item':<10} {'Bid':>7} {'Ask':>7} {'Sprd':>7}\n"
    DIV  = f"{'─'*10} {'─'*7} {'─'*7} {'─'*7}\n"
    body = HDR + DIV
    for s in spreads:
        short = mkt.ITEM_SHORT.get(s["item"], s["item"][:10])
        bid   = f"{s['best_bid']:.4f}" if s["best_bid"] is not None else "  —  "
        ask   = f"{s['best_ask']:.4f}" if s["best_ask"] is not None else "  —  "
        sprd  = f"{s['spread']:.4f}"   if s["spread"]   is not None else "  —  "
        flag  = "!" if (s["spread"] is not None and s["spread"] < 0) else ("*" if (s["spread"] is not None and s["spread"] == 0) else "")
        body += f"{short:<10} {bid:>7} {ask:>7} {sprd:>7}{flag}\n"
    e = _embed("📊 Market — Spread", discord.Color.dark_teal())
    e.description = f"```\n{body}```"
    e.set_footer(text="* = zero spread  ! = crossed book  •  sorted by spread asc  •  bwabwabwa")
    return e


def build_volume_embed(volume: dict[str, dict]) -> discord.Embed:
    HDR  = f"{'Item':<10} {'tx':>5} {'qty':>7} {'qty/h':>7}\n"
    DIV  = f"{'─'*10} {'─'*5} {'─'*7} {'─'*7}\n"
    body = HDR + DIV
    for item_name, v in sorted(volume.items(), key=lambda x: x[1]["qty"], reverse=True):
        short = mkt.ITEM_SHORT.get(item_name, item_name[:10])
        body += f"{short:<10} {_fmt_compact(v['tx']):>5} {_fmt_compact(v['qty']):>7} {_fmt_compact(v['qty_h']):>7}\n"
    e = _embed("🔥 Market — Volume (24h)", discord.Color.orange())
    e.description = f"```\n{body}```"
    e.set_footer(text="tx = transactions  •  qty = total units  •  qty/h = avg per hour  •  bwabwabwa")
    return e


# --- history / best time ---

def build_history_embed(name: str, days: int, data: list[dict]) -> discord.Embed:
    prices  = [d["price"] for d in data]
    current = prices[-1]
    avg     = sum(prices) / len(prices)
    high    = max(prices)
    low     = min(prices)
    chg_pct = ((current - avg) / avg) * 100 if avg else 0
    sign        = "+" if chg_pct >= 0 else ""
    trend_emoji = "🟢" if chg_pct > 1 else ("🔴" if chg_pct < -1 else "⚪")
    trend_label = f"{trend_emoji} {sign}{_fmt_pct(chg_pct)}% vs avg"

    daily: dict[str, list] = defaultdict(list)
    for d in data:
        daily[d["recorded_at"][:10]].append(d["price"])
    daily_avg = {day: sum(v)/len(v) for day, v in sorted(daily.items())}

    e = _embed(f"📈 Price History ({days}d) — {name}", discord.Color.blue())
    e.add_field(name="Current Price",  value=f"`{_fmt_price(current)}`", inline=True)
    e.add_field(name=f"Avg ({days}d)", value=f"`{_fmt_price(avg)}`",     inline=True)
    e.add_field(name="Change",         value=trend_label,                 inline=False)
    e.add_field(name="High",           value=f"`{_fmt_price(high)}`",     inline=True)
    e.add_field(name="Low",            value=f"`{_fmt_price(low)}`",      inline=True)
    e.add_field(name="Data Points",    value=f"`{len(prices):,}`",        inline=True)
    if daily_avg:
        e.add_field(
            name="Daily Average",
            value="\n".join(f"`{day}` → `{_fmt_price(p)}`" for day, p in list(daily_avg.items())[-30:]),
            inline=False,
        )
    return e


def build_bestime_embed(name: str, data: list[dict]) -> discord.Embed:
    e = _embed(f"⏰ Best Time to Sell — {name}", discord.Color.green())
    if len(data) < 24:
        e.description = f"⚠️ Insufficient data (`{len(data)}` points). Bot needs to run a few more days."
        return e

    hourly: dict[int, list] = defaultdict(list)
    for d in data:
        try:
            hourly[int(d["recorded_at"][11:13])].append(d["price"])
        except (IndexError, ValueError):
            continue
    if not hourly:
        e.description = "⚠️ Unable to process history data."
        return e

    hourly_avg   = {h: sum(v)/len(v) for h, v in hourly.items()}
    sorted_hours = sorted(hourly_avg.items(), key=lambda x: x[1], reverse=True)
    best, worst  = sorted_hours[0], sorted_hours[-1]
    diff_pct     = ((best[1] - worst[1]) / worst[1]) * 100 if worst[1] else 0

    e.add_field(
        name="🏆 Best Hours (UTC)",
        value="\n".join(f"`{h:02d}:00`  avg: `{_fmt_price(a)}`" for h, a in sorted_hours[:3]),
        inline=True,
    )
    e.add_field(
        name="📉 Worst Hours (UTC)",
        value="\n".join(f"`{h:02d}:00`  avg: `{_fmt_price(a)}`" for h, a in sorted_hours[-3:][::-1]),
        inline=True,
    )
    e.add_field(
        name="Best vs Worst",
        value=f"`{_fmt_pct(diff_pct)}%` — {'significant' if diff_pct > 2 else 'minor, price relatively stable'}",
        inline=False,
    )
    e.add_field(name="Note", value="Times in UTC. Accuracy improves as bot runs longer.", inline=False)
    return e


# --- equipment ---

def build_craft_table(ps: float, pt: float) -> str:
    header  = f"{'Grade':<12}{'Mode':<10}{'Value':>12}"
    divider = "─" * len(header)
    rows    = [header, divider]
    for grade, d in mkt.EQUIPMENT_GRADES.items():
        s, st = d["craft_scraps"], d["craft_steel"]
        rows.append(f"{grade:<12}{'Random':<10}{_fmt_money((s*ps)+(st*pt)):>12}")
        rows.append(f"{'':<12}{'Choose':<10}{_fmt_money((s*ps)+((st*2)*pt)):>12}")
    return "```\n" + "\n".join(rows) + "\n```"


def build_dismantle_table(ps: float) -> str:
    header  = f"{'Grade':<12}{'Scraps':<10}{'Value':>12}"
    divider = "─" * len(header)
    rows    = [header, divider]
    for grade, d in mkt.EQUIPMENT_GRADES.items():
        ds = d["dismantle_scraps"]
        rows.append(f"{grade:<12}{ds:<10,}{_fmt_money(ds*ps):>12}")
    return "```\n" + "\n".join(rows) + "\n```"


def build_equipment_embed(page: int, ps: float, pt: float) -> discord.Embed:
    if page == 1:
        e = _embed("⚒️ WarEra Equipment Calculator", discord.Color.gold())
        e.description = (
            "**Crafting Cost vs Market  •  Page 1 of 2**\n\n"
            + build_craft_table(ps, pt)
            + "\n**Random** = random item type at chosen grade.\n"
            "**Choose** = pick specific item type (Steel ×2).\n"
            "All values in gold based on current market price."
        )
        e.set_footer(text=f"Scraps: {_fmt_money(ps)} g  •  Steel: {_fmt_money(pt)} g  •  bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    else:
        e = _embed("⚒️ WarEra Equipment Calculator", discord.Color.purple())
        e.description = (
            "**Dismantle Value vs Market  •  Page 2 of 2**\n\n"
            + build_dismantle_table(ps)
            + "\n**Scraps** = amount received when dismantling.\n"
            "**Value** = Scraps × current market price."
        )
        e.set_footer(text=f"Scraps: {_fmt_money(ps)} g  •  bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    return e


# --- donation ---

def make_weekly_columns(
    donor_rows: list[tuple[str, float]],
    grand_total: float,
    page_start: int,
    per_col_cap: int,
    max_cols: int,
) -> list[tuple[str, list[tuple[int, str, str, Optional[str]]]]]:
    """Pecah satu halaman donor_rows jadi 1-3 kolom (maks per_col_cap baris).
    page_start = rank awal (0-based) halaman ini."""
    columns: list[tuple[str, list[tuple[int, str, str, Optional[str]]]]] = []
    for c in range(max_cols):
        chunk = donor_rows[c * per_col_cap:(c + 1) * per_col_cap]
        if not chunk:
            break
        rows: list[tuple[int, str, str, Optional[str]]] = []
        for i, (uname, total) in enumerate(chunk):
            rank = page_start + c * per_col_cap + i + 1
            pct  = (total / grand_total * 100) if grand_total else 0
            rows.append((rank, uname, _fmt_money(total), f"{_fmt_pct(pct)}%"))
        start_rank = page_start + c * per_col_cap + 1
        end_rank   = start_rank + len(chunk) - 1
        columns.append((f"Rank {start_rank}-{end_rank}", rows))
    return columns


def build_donation_weekly_specs(
    range_label: str,
    donor_rows: list[tuple[str, float]],
    grand_total: float,
    per_col_cap: int,
    max_cols: int,
    page_cap: int,
) -> list[dict]:
    """Bikin list of kwargs (subtitle, columns) buat vis.generate_donation_image
    — 1 halaman per page_cap donatur, kolom otomatis 1-3."""
    if not donor_rows:
        return [{
            "subtitle": f"{range_label}  •  Total Donor: 0  •  Total: 0g",
            "columns": [("Rank 1-0", [])],
        }]

    total_pages = (len(donor_rows) + page_cap - 1) // page_cap
    specs: list[dict] = []
    for p, start in enumerate(range(0, len(donor_rows), page_cap)):
        page_rows = donor_rows[start:start + page_cap]
        columns   = make_weekly_columns(page_rows, grand_total, start, per_col_cap, max_cols)
        subtitle  = (
            f"{range_label}  •  Total Donor: {len(donor_rows)}  •  "
            f"Total: {_fmt_money(grand_total)}g"
        )
        if total_pages > 1:
            subtitle += f"  •  Page {p + 1}/{total_pages}"
        specs.append({"subtitle": subtitle, "columns": columns})
    return specs


def build_donation_daily_specs(
    sorted_days_desc: list[str],
    daily_map: dict[str, list[tuple[str, float]]],
    max_cols: int,
) -> list[dict]:
    """Bikin list of kwargs buat vis.generate_donation_image — max_cols (3)
    tanggal per halaman, top 15/hari (dipotong di group_donations_by_day)."""
    if not sorted_days_desc:
        return []

    total_days  = len(sorted_days_desc)
    total_pages = (total_days + max_cols - 1) // max_cols
    specs: list[dict] = []

    for p, start in enumerate(range(0, total_days, max_cols)):
        day_chunk = sorted_days_desc[start:start + max_cols]
        columns: list[tuple[str, list[tuple[int, str, str, Optional[str]]]]] = []
        for date_str in day_chunk:
            try:
                label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%y")
            except ValueError:
                label = date_str
            ranked = daily_map.get(date_str, [])
            rows = [
                (i + 1, uname, _fmt_money(total), None)
                for i, (uname, total) in enumerate(ranked)
            ]
            columns.append((label, rows))

        subtitle = f"Daily Donations — Top 15/day  •  Page {p + 1}/{total_pages}"
        specs.append({"subtitle": subtitle, "columns": columns})
    return specs
