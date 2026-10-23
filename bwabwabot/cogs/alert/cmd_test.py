"""
cogs/alerts/cmd_test.py  —  xalert test  (kirim dummy alert dari tiap jenis)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from discord.ext import commands

from .base import AlertsBase
from .cmd_root import cmd_alert
from .embeds import build_war_embed, build_orders_embed, build_ground_embed, build_bonus_embed, build_orderbook_embed


class TestCommands(AlertsBase):

    @cmd_alert.command(name="test")
    async def alert_test(self, ctx: commands.Context) -> None:
        country_cache_test = {
            "d_att":  "Australia 🇦🇺",
            "d_def":  "Laos 🇱🇦",
            "d_ally": "Thailand 🇹🇭",
        }
        mu_cache_test = {"d_mu": "Lao Guardian"}

        _, e1 = build_war_embed(
            region_name="Bekasi",
            war_type="war",
            battle_id="6a40e4485ea048fe8cf9b2a4",
            attacker_name="Alien",
            defender_name="Laos 🇱🇦",
            attacker_dmg=821_241_977,
            defender_dmg=808_967_411,
            att_country_orders=["d_att", "d_ally"],
            def_country_orders=["d_def"],
            att_country_id="d_att",
            def_country_id="d_def",
            bounty_attacker=None,
            bounty_defender=2.5,
            started_at="2026-06-27T23:37:00Z",
            country_cache=country_cache_test,
            mu_cache=mu_cache_test,
        )
        await ctx.send(content="**[TEST] Type 1 — War Alert:**", embed=e1)

        _, e2 = build_orders_embed(
            new_orders=[
                {
                    "order_id":           "d_def",
                    "order_type":         "country",
                    "side":               "defender",
                    "region_name":        "Cayenne",
                    "battle_id":          "6a40e4485ea048fe8cf9b2a4",
                    "attacker_country":   "d_att",
                    "defender_country":   "d_def",
                    "att_country_orders": ["d_att", "d_ally"],
                    "def_country_orders": ["d_def"],
                },
            ],
            country_cache=country_cache_test,
            mu_cache=mu_cache_test,
        )
        await ctx.send(content="**[TEST] Type 2 — Order Alert:**", embed=e2)

        _, e3 = build_ground_embed(
            region_name="Sekong",
            round_number=2,
            battle_id="6a40e4485ea048fe8cf9b2a4",
            attacker_name="Australia 🇦🇺",
            defender_name="Laos 🇱🇦",
            attacker_points=232,
            defender_points=5,
            attacker_dmg=2_084_710,
            defender_dmg=174_303,
            att_country_orders=["d_att", "d_ally"],
            def_country_orders=["d_def"],
            att_country_id="d_att",
            def_country_id="d_def",
            country_cache=country_cache_test,
            mu_cache=mu_cache_test,
        )
        await ctx.send(content="**[TEST] Ground Alert:**", embed=e3)

        _, e4 = build_bonus_embed(
            item_label="Grain",
            old_country="Indonesia 🇮🇩",
            old_pct=60.0,
            old_country_now_pct=45.55,
            new_top_country="Laos 🇱🇦",
            new_top_pct=63.0,
            new_top_ends_at=datetime.now(timezone.utc) + timedelta(hours=14, minutes=20),
        )
        await ctx.send(content="**[TEST] Type 3 — Production Bonus Alert:**", embed=e4)

        _, e5 = build_orderbook_embed(
            item_label="Iron",
            direction="buy_heavy",
            ratio=3.2,
            threshold=2.0,
            bid_qty=500000, bid_price=0.087,
            ask_qty=156250, ask_price=0.086,
        )
        await ctx.send(content="**[TEST] Type 4 — Order Book Alert:**", embed=e5)
