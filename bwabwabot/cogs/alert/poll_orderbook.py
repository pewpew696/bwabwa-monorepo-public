"""
cogs/alerts/poll_orderbook.py  —  Task loop poll_orderbook: Type 4 (Order Book Imbalance Alert).

Trigger: total qty 3 level harga terbaik (top-3 bid vs top-3 ask) timpang >=
ratio (2 arah). Ratio per config bisa di-override lewat custom_ratio
(xalert add book <item> <N>x); kalau NULL pakai ORDERBOOK_ALERT_RATIO (default).

Aturan alert (per guild + item + threshold):
- Rasio >= threshold dan belum pernah alert            -> alert.
- Arah berbalik (buy_heavy <-> sell_heavy)             -> alert langsung,
  tanpa nunggu cooldown.
- Arah sama                                            -> alert lagi hanya
  kalau sudah lewat ORDERBOOK_ALERT_COOLDOWN_H jam sejak alert terakhir.
- Rasio turun di bawah threshold TIDAK mereset cache (cooldown tetap jalan).
- Siklus pertama setelah bot start: kombinasi yang belum punya cache cuma
  di-seed diam-diam (anti banjir alert saat restart/deploy). Setelah itu
  crossing pertama langsung alert.

Baris target_id spesifik (mis. "iron") MENIMPA baris "all" untuk item itu
di guild yang sama -- "all" cuma berlaku buat item yang belum ada baris
spesifiknya di guild tsb.

Cache (_orderbook_cache, tabel orderbook_alert_cache) di-key per
(guild_id, item_id, ratio_threshold); value = (direction, ratio, alerted_at).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from discord.ext import commands, tasks

from .base import (
    AlertsBase, log, _resolve_resource,
    ORDERBOOK_POLL_INTERVAL_MIN, ORDERBOOK_ALERT_RATIO,
    ORDERBOOK_ALERT_COOLDOWN_H, ORDERBOOK_DEPTH_LEVELS,
)
from .embeds import build_orderbook_embed


class PollOrderbookCommands(AlertsBase):

    @tasks.loop(minutes=ORDERBOOK_POLL_INTERVAL_MIN)
    async def poll_orderbook(self) -> None:
        try:
            # True = siklus pertama sudah lewat -> crossing baru boleh alert.
            seeded = getattr(self, "_orderbook_seeded", False)

            configs4 = await self._get_configs(4)
            if not configs4:
                self._orderbook_seeded = True
                return

            import market as mkt

            # --- Resolve item_id per config (target_id "all" ditangani terpisah) ---
            specific_by_guild: dict[str, set[str]] = {}
            for c in configs4:
                if c["target_id"] != "all":
                    specific_by_guild.setdefault(c["guild_id"], set()).add(c["target_id"])

            # Union semua item_id yang perlu di-fetch siklus ini.
            item_ids: set[str] = set()
            watch_all = any(c["target_id"] == "all" for c in configs4)
            for c in configs4:
                if c["target_id"] != "all":
                    item_ids.add(c["target_id"])
            if watch_all:
                item_ids.update(mkt.ITEM_LABELS.keys())

            if not item_ids:
                self._orderbook_seeded = True
                return

            # --- Fetch semua item paralel, HEADERS polos (fetch_orderbook tanpa token) ---
            async def _fetch(item_id: str):
                label = mkt.ITEM_LABELS.get(item_id, item_id)
                ob = await mkt.fetch_orderbook(self._session, label)
                return item_id, ob

            results = await asyncio.gather(*(_fetch(i) for i in item_ids))

            depth    = max(1, int(ORDERBOOK_DEPTH_LEVELS))
            cooldown = timedelta(hours=ORDERBOOK_ALERT_COOLDOWN_H)

            for item_id, ob in results:
                if not ob:
                    continue
                bids, asks = ob.get("bids") or [], ob.get("asks") or []
                # Guard: skip item yang salah satu sisinya kosong (illiquid) --
                # rasio jadi tak-terhingga/tak-berarti, bukan sinyal beneran.
                if not bids or not asks:
                    continue

                # Gabungan qty maksimal `depth` level harga terbaik per sisi.
                # Kalau level kurang dari `depth`, pakai yang ada.
                bid_qty = sum(lv["qty"] for lv in bids[:depth])
                ask_qty = sum(lv["qty"] for lv in asks[:depth])
                bid_price = bids[0]["price"]
                ask_price = asks[0]["price"]
                if bid_qty <= 0 or ask_qty <= 0:
                    continue

                if bid_qty >= ask_qty:
                    direction, ratio = "buy_heavy", bid_qty / ask_qty
                else:
                    direction, ratio = "sell_heavy", ask_qty / bid_qty

                # Config mana saja yang relevan buat item ini, dengan aturan
                # "baris spesifik menimpa baris all" per guild.
                targets = []
                for c in configs4:
                    if c["target_id"] == item_id:
                        targets.append(c)
                    elif c["target_id"] == "all":
                        watched_specific = specific_by_guild.get(c["guild_id"], set())
                        if item_id not in watched_specific:
                            targets.append(c)

                for cfg in targets:
                    threshold = float(cfg.get("custom_ratio") or ORDERBOOK_ALERT_RATIO)
                    if ratio < threshold:
                        # Di bawah threshold: tidak alert, cache TIDAK dihapus
                        # supaya cooldown tetap berlaku kalau rasio naik lagi.
                        continue

                    guild_id  = str(cfg["guild_id"])
                    cache_key = (guild_id, item_id, threshold)
                    old = self._orderbook_cache.get(cache_key)

                    if old is None:
                        if not seeded:
                            # Siklus pertama pasca-start: seed diam-diam.
                            await self._set_orderbook_cache(
                                guild_id, item_id, threshold, direction, ratio
                            )
                            continue
                        # Sudah lewat siklus pertama -> crossing pertama = alert.
                    else:
                        old_direction, _old_ratio, old_at = old
                        now = datetime.now(timezone.utc)
                        if direction == old_direction and (now - old_at) < cooldown:
                            continue  # arah sama & masih cooldown

                    channel = self.bot.get_channel(int(cfg["channel_id"]))
                    if not channel:
                        continue
                    ping, embed = build_orderbook_embed(
                        item_label=ob.get("item", item_id),
                        direction=direction,
                        ratio=ratio,
                        threshold=threshold,
                        bid_qty=bid_qty, bid_price=bid_price,
                        ask_qty=ask_qty, ask_price=ask_price,
                        role_ping=cfg.get("role_ping"),
                    )
                    try:
                        from .alert_mute import guarded_alert_send  # boot-fix: kirim via auto-mute guard
                        sent = await guarded_alert_send(channel, content=ping or None, embed=embed)
                        if sent is not None:
                            await self._queue_alert_delete(sent)
                    except Exception as exc:
                        log.warning(f"Orderbook alert send: {exc}")

                    await self._set_orderbook_cache(guild_id, item_id, threshold, direction, ratio)

            self._orderbook_seeded = True

        except Exception as exc:
            log.error(f"poll_orderbook: {exc}", exc_info=True)

    @poll_orderbook.before_loop
    async def _before_poll_orderbook(self) -> None:
        await self.bot.wait_until_ready()
