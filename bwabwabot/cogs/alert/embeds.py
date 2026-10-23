"""
cogs/alerts/embeds.py  —  Fungsi pembangun discord.Embed untuk tiap jenis alert.
"""

from __future__ import annotations

from datetime import datetime, timezone

import discord

from .base import _fmt_k, _utc_str, _fmt_pct_id, _bounty_str, _orders_field, BONUS_ALERT_EPSILON


def build_war_embed(
    region_name: str,
    war_type: str,
    battle_id: str,
    attacker_name: str,
    defender_name: str,
    attacker_dmg: float,
    defender_dmg: float,
    att_country_orders: list,
    def_country_orders: list,
    att_country_id: str,
    def_country_id: str,
    bounty_attacker,
    bounty_defender,
    started_at: str | None,
    country_cache: dict,
    mu_cache: dict,
    role_ping: str | None = None,
) -> tuple[str, discord.Embed]:
    battle_link = f"https://app.warera.io/battle/{battle_id}"
    e = discord.Embed(title="🚨 BATTLE ALERT 🚨", color=discord.Color.red())
    e.add_field(name="🗺️ Region", value=f"**{region_name}**",        inline=True)
    e.add_field(name="⚔️ Type",   value=war_type.title(),            inline=True)
    e.add_field(name="🔗 Link",   value=f"[Buka Battle]({battle_link})", inline=True)

    def_orders_str = _orders_field(
        def_country_orders,
        country_cache, mu_cache,
        direct_country_id=def_country_id,
    )
    att_orders_str = _orders_field(
        att_country_orders,
        country_cache, mu_cache,
        direct_country_id=att_country_id,
    )

    e.add_field(
        name=f"🛡️ Defender: {defender_name}",
        value=(
            f"{def_orders_str}\n"
            f"💥 Damage: `{_fmt_k(defender_dmg)}`\n"
            f"💰 Bounty: `{_bounty_str(bounty_defender)}`"
        ),
        inline=True,
    )
    e.add_field(
        name=f"🗡️ Attacker: {attacker_name}",
        value=(
            f"{att_orders_str}\n"
            f"💥 Damage: `{_fmt_k(attacker_dmg)}`\n"
            f"💰 Bounty: `{_bounty_str(bounty_attacker)}`"
        ),
        inline=True,
    )
    e.add_field(name="\u200b", value="\u200b", inline=True)
    e.add_field(name="⏰ Started", value=_utc_str(started_at), inline=False)
    e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    ping_str = " ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) + "\n" if role_ping else ""
    return ping_str, e


def build_orders_embed(
    new_orders: list[dict],
    country_cache: dict,
    mu_cache: dict,
    role_ping: str | None = None,
) -> tuple[str, discord.Embed]:
    e = discord.Embed(title="📋 ORDER ALERT 📋", color=discord.Color.orange())

    by_region: dict[str, list[dict]] = {}
    for o in new_orders:
        rname = o.get("region_name", "Unknown")
        by_region.setdefault(rname, []).append(o)

    for region_name, orders in by_region.items():
        o0          = orders[0]
        battle_id   = o0.get("battle_id", "")
        att_id      = o0.get("attacker_country", "")
        def_id      = o0.get("defender_country", "")
        att_country = country_cache.get(att_id, "?")
        def_country = country_cache.get(def_id, "?")

        def_orders_str = _orders_field(
            o0.get("def_country_orders", []),
            country_cache, mu_cache,
            direct_country_id=def_id,
        )
        att_orders_str = _orders_field(
            o0.get("att_country_orders", []),
            country_cache, mu_cache,
            direct_country_id=att_id,
        )

        battle_link = f"https://app.warera.io/battle/{battle_id}"
        val = (
            f"🛡️ **Defender: {def_country}**\n{def_orders_str}\n"
            f"🗡️ **Attacker: {att_country}**\n{att_orders_str}\n"
            f"🔗 [Buka Battle]({battle_link})"
        )
        e.add_field(name=f"🗺️ {region_name}", value=val, inline=False)

    e.add_field(name="⏰", value=_utc_str(datetime.now(timezone.utc).isoformat()), inline=False)
    e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    ping_str = " ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) + "\n" if role_ping else ""
    return ping_str, e


def build_ground_embed(
    region_name: str,
    round_number,
    battle_id: str,
    attacker_name: str,
    defender_name: str,
    attacker_points: float,
    defender_points: float,
    attacker_dmg: float,
    defender_dmg: float,
    att_country_orders: list,
    def_country_orders: list,
    att_country_id: str,
    def_country_id: str,
    country_cache: dict,
    mu_cache: dict,
    role_ping: str | None = None,
) -> tuple[str, discord.Embed]:
    battle_link = f"https://app.warera.io/battle/{battle_id}"
    e = discord.Embed(title="⚠️ GROUND ALERT ⚠️", color=discord.Color.dark_orange())
    e.add_field(name="🗺️ Region", value=f"**{region_name}**",           inline=True)
    e.add_field(name="🔄 Round",  value=f"#{round_number}",              inline=True)
    e.add_field(name="🔗 Link",   value=f"[Buka Battle]({battle_link})", inline=True)

    def_orders_str = _orders_field(
        def_country_orders,
        country_cache, mu_cache,
        direct_country_id=def_country_id,
    )
    att_orders_str = _orders_field(
        att_country_orders,
        country_cache, mu_cache,
        direct_country_id=att_country_id,
    )

    e.add_field(
        name=f"🛡️ Defender: {defender_name}",
        value=(
            f"{def_orders_str}\n"
            f"📊 Ground: `{defender_points:.0f}`\n"
            f"💥 Dmg: `{_fmt_k(defender_dmg)}`"
        ),
        inline=True,
    )
    e.add_field(
        name=f"🗡️ Attacker: {attacker_name}",
        value=(
            f"{att_orders_str}\n"
            f"📊 Ground: `{attacker_points:.0f}`\n"
            f"💥 Dmg: `{_fmt_k(attacker_dmg)}`"
        ),
        inline=True,
    )
    e.add_field(name="\u200b", value="\u200b", inline=True)
    e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    ping_str = " ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) + "\n" if role_ping else ""
    return ping_str, e


def build_bonus_embed(
    item_label: str,
    old_country: str,
    old_pct: float,
    old_country_now_pct: float,
    new_top_country: str,
    new_top_pct: float,
    role_ping: str | None = None,
    new_top_ends_at: datetime | None = None,
) -> tuple[str, discord.Embed]:
    e = discord.Embed(title="🏭 PRODUCTION BONUS ALERT 🏭", color=discord.Color.green())

    lines = []
    same_country  = old_country == new_top_country
    value_changed = abs(old_pct - old_country_now_pct) > BONUS_ALERT_EPSILON
    if not same_country or value_changed:
        lines.append(
            f"📉 **{item_label}** production bonus in **{old_country}** was "
            f"`{_fmt_pct_id(old_pct)}%`, now `{_fmt_pct_id(old_country_now_pct)}%`"
        )
    top_line = (
        f"🏆 The highest **{item_label}** production bonus is currently in **{new_top_country}** "
        f"at `{_fmt_pct_id(new_top_pct)}%`"
    )
    # Durasi cuma ada kalau bonus top-1 datang dari deposit (bonus negara/partai gak punya
    # masa berlaku di API). Teks UTC statis + timestamp Discord yang hitung mundur sendiri —
    # pesan alert bertahan 12 jam, teks relatif statis bakal basi.
    if new_top_ends_at:
        top_line += (
            f"  ⏳ ends {_utc_str(new_top_ends_at.isoformat())} "
            f"(<t:{int(new_top_ends_at.timestamp())}:R>)"
        )
    lines.append(top_line)
    e.description = "\n".join(lines)
    e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    ping_str = " ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) + "\n" if role_ping else ""
    return ping_str, e


def build_orderbook_embed(
    item_label: str,
    direction: str,
    ratio: float,
    threshold: float,
    bid_qty: float,
    bid_price: float,
    ask_qty: float,
    ask_price: float,
    role_ping: str | None = None,
) -> tuple[str, discord.Embed]:
    heavy_side  = "🟢 BUY" if direction == "buy_heavy" else "🔴 SELL"
    title_color = discord.Color.green() if direction == "buy_heavy" else discord.Color.red()

    e = discord.Embed(title="⚖️ ORDER BOOK ALERT ⚖️", color=title_color)
    e.add_field(name="📦 Item", value=f"**{item_label}**", inline=True)
    e.add_field(name="⚡ Heavier Side", value=heavy_side, inline=True)
    e.add_field(name="📊 Ratio", value=f"`{ratio:.2f}x` (threshold `{threshold:.2f}x`)", inline=True)
    e.add_field(
        name="🟢 Top 3 Bid",
        value=f"Qty: `{_fmt_k(bid_qty)}`\nBest Price: `{bid_price}`",
        inline=True,
    )
    e.add_field(
        name="🔴 Top 3 Ask",
        value=f"Qty: `{_fmt_k(ask_qty)}`\nBest Price: `{ask_price}`",
        inline=True,
    )
    e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    ping_str = " ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) + "\n" if role_ping else ""
    return ping_str, e
