"""
cogs/alerts/poll_war.py  —  Task loop poll_wars: Type 1 (War Alert),
Ground Alert, dan Type 2 (Order Alert).

Ketiganya digabung dalam SATU task loop karena sama-sama bersumber dari
satu kali fetch `region.getRegionsObject` (lihat AlertsBase._fetch_regions_object)
— dipisah jadi 3 loop terpisah cuma bakal bikin fetch API berulang untuk
data yang sama.
"""

from __future__ import annotations

from discord.ext import commands, tasks

from .base import AlertsBase, log, POLL_INTERVAL_MIN, GROUND_ALERT_THRESHOLD
from .embeds import build_war_embed, build_ground_embed, build_orders_embed


class PollWarCommands(AlertsBase):

    @tasks.loop(minutes=POLL_INTERVAL_MIN)
    async def poll_wars(self) -> None:
        try:
            configs1 = await self._get_configs(1)
            configs2 = await self._get_configs(2)
            log.info(f"[POLL] Type1: {len(configs1)}, Type2: {len(configs2)}")

            if not configs1 and not configs2:
                return

            type1_targets = {c["target_id"] for c in configs1}
            type2_targets = {c["target_id"] for c in configs2}

            # Satu fetch untuk kedua jenis alert
            regions_obj = await self._fetch_regions_object()
            log.info(f"[POLL] Regions: {len(regions_obj)}")

            guild_orders: dict[str, list[dict]] = {}

            for region in regions_obj.values():
                if not region:
                    continue
                battle = region.get("activeBattle")
                if not battle:
                    continue

                battle_id   = battle.get("_id", "")
                region_name = region.get("name", "Unknown Region")
                if not battle_id:
                    continue

                att_side = battle.get("attacker") or {}
                def_side = battle.get("defender") or {}
                att_id   = att_side.get("country", "")
                def_id   = def_side.get("country", "")

                att_country_orders = [x for x in (att_side.get("countryOrders") or []) if isinstance(x, str)]
                att_mu_orders      = [x for x in (att_side.get("muOrders")      or []) if isinstance(x, str)]
                def_country_orders = [x for x in (def_side.get("countryOrders") or []) if isinstance(x, str)]
                def_mu_orders      = [x for x in (def_side.get("muOrders")      or []) if isinstance(x, str)]

                # Resolve nama MU yang belum di-cache
                all_mu_ids = att_mu_orders + def_mu_orders
                if all_mu_ids:
                    await self._resolve_mu_names_batch(all_mu_ids)

                # --- Type 1: War Alert ---
                if type1_targets and ({att_id, def_id} & type1_targets) and battle_id not in self._war_alerted:
                    bounty_info = battle.get("bounty") or {}
                    bounty_att  = bounty_info.get("attackerBounty") if isinstance(bounty_info, dict) else None
                    bounty_def  = bounty_info.get("defenderBounty") if isinstance(bounty_info, dict) else None
                    att_name    = self._country_cache.get(att_id, att_id[:8] + "...")
                    def_name    = self._country_cache.get(def_id, def_id[:8] + "...")
                    war_type    = battle.get("type", "war")

                    for cfg in configs1:
                        if cfg["target_id"] not in {att_id, def_id}:
                            continue
                        channel = self.bot.get_channel(int(cfg["channel_id"]))
                        if not channel:
                            continue
                        ping, embed = build_war_embed(
                            region_name=region_name,
                            war_type=war_type,
                            battle_id=battle_id,
                            attacker_name=att_name,
                            defender_name=def_name,
                            attacker_dmg=float(att_side.get("damages") or 0),
                            defender_dmg=float(def_side.get("damages") or 0),
                            att_country_orders=att_country_orders,
                            def_country_orders=def_country_orders,
                            att_country_id=att_id,
                            def_country_id=def_id,
                            bounty_attacker=bounty_att,
                            bounty_defender=bounty_def,
                            started_at=battle.get("createdAt"),
                            country_cache=self._country_cache,
                            mu_cache=self._mu_cache,
                            role_ping=cfg.get("role_ping"),
                        )
                        try:
                            from .alert_mute import guarded_alert_send  # boot-fix: auto-mute guard
                            sent = await guarded_alert_send(channel, content=ping or None, embed=embed)
                            if sent is not None:
                                await self._queue_alert_delete(sent)
                        except Exception as exc:
                            log.warning(f"Type1 send: {exc}")

                    await self._mark_war_alerted(battle_id)

                # --- Ground Alert: round hampir selesai (>220 poin) ---
                if type1_targets and ({att_id, def_id} & type1_targets):
                    current_round_id = battle.get("currentRound")
                    if current_round_id and current_round_id not in self._ground_alerted:
                        import market as mkt
                        round_data = await mkt.fetch_round(self._session, current_round_id)
                        if round_data:
                            r_att = round_data.get("attacker") or {}
                            r_def = round_data.get("defender") or {}
                            att_pts = float(r_att.get("points") or 0)
                            def_pts = float(r_def.get("points") or 0)

                            if att_pts > GROUND_ALERT_THRESHOLD or def_pts > GROUND_ALERT_THRESHOLD:
                                att_name = self._country_cache.get(att_id, att_id[:8] + "...")
                                def_name = self._country_cache.get(def_id, def_id[:8] + "...")
                                round_number = round_data.get("number", "?")

                                for cfg in configs1:
                                    if cfg["target_id"] not in {att_id, def_id}:
                                        continue
                                    channel = self.bot.get_channel(int(cfg["channel_id"]))
                                    if not channel:
                                        continue
                                    ping, embed = build_ground_embed(
                                        region_name=region_name,
                                        round_number=round_number,
                                        battle_id=battle_id,
                                        attacker_name=att_name,
                                        defender_name=def_name,
                                        attacker_points=att_pts,
                                        defender_points=def_pts,
                                        attacker_dmg=float(r_att.get("damages") or 0),
                                        defender_dmg=float(r_def.get("damages") or 0),
                                        att_country_orders=att_country_orders,
                                        def_country_orders=def_country_orders,
                                        att_country_id=att_id,
                                        def_country_id=def_id,
                                        country_cache=self._country_cache,
                                        mu_cache=self._mu_cache,
                                        role_ping=cfg.get("role_ping"),
                                    )
                                    try:
                                        from .alert_mute import guarded_alert_send  # boot-fix: auto-mute guard
                                        sent = await guarded_alert_send(channel, content=ping or None, embed=embed)
                                        if sent is not None:
                                            await self._queue_alert_delete(sent)
                                    except Exception as exc:
                                        log.warning(f"Ground alert send: {exc}")

                                await self._mark_ground_alerted(current_round_id, battle_id)

                # --- Type 2: Order Alert ---
                if type2_targets:
                    side_defs = [
                        ("attacker", att_country_orders, att_mu_orders),
                        ("defender", def_country_orders, def_mu_orders),
                    ]
                    for side_label, country_orders, mu_orders in side_defs:
                        for otype, raw_list in (("country", country_orders), ("mu", mu_orders)):
                            for raw_id in raw_list:
                                cache_key = f"{battle_id}:{raw_id}"
                                if cache_key in self._order_alerted:
                                    continue
                                if raw_id not in type2_targets:
                                    self._order_alerted.add(cache_key)
                                    continue

                                log.info(
                                    f"[POLL] ORDER MATCH! battle={battle_id} "
                                    f"region={region_name} id={raw_id} side={side_label}"
                                )
                                enriched = {
                                    "order_id":          raw_id,
                                    "order_type":        otype,
                                    "side":              side_label,
                                    "region_name":       region_name,
                                    "battle_id":         battle_id,
                                    "attacker_country":  att_id,
                                    "defender_country":  def_id,
                                    "att_country_orders": att_country_orders,
                                    "def_country_orders": def_country_orders,
                                }
                                for cfg in configs2:
                                    if cfg["target_id"] != raw_id:
                                        continue
                                    gid = cfg["guild_id"]
                                    guild_orders.setdefault(gid, []).append({**enriched, "cfg": cfg})
                                await self._mark_order_alerted(battle_id, raw_id)

            # Kirim semua Order Alert yang terkumpul
            for guild_id, orders in guild_orders.items():
                by_channel: dict[str, list] = {}
                for o in orders:
                    cid = o["cfg"]["channel_id"]
                    by_channel.setdefault(cid, []).append(o)
                for channel_id, ch_orders in by_channel.items():
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        continue
                    role_ping = ch_orders[0]["cfg"].get("role_ping")
                    ping, embed = build_orders_embed(
                        new_orders=ch_orders,
                        country_cache=self._country_cache,
                        mu_cache=self._mu_cache,
                        role_ping=role_ping,
                    )
                    try:
                        from .alert_mute import guarded_alert_send  # boot-fix: auto-mute guard
                        sent = await guarded_alert_send(channel, content=ping or None, embed=embed)
                        if sent is not None:
                            await self._queue_alert_delete(sent)
                    except Exception as exc:
                        log.warning(f"Type2 send: {exc}")

        except Exception as exc:
            log.error(f"poll_wars: {exc}", exc_info=True)

    @poll_wars.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()