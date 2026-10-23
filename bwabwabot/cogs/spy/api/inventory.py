"""cogs/spy/api/inventory.py — tracking inventory via transaction history, cache app_db."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger("WarEraBot.spy")


class InventoryMixin:
    """Mixin — expects self._session dari class final."""

    INVENTORY_CACHE_TTL_HOURS = 6

    # --- inventory equipment tracking (backend buat web) ---

    async def _fetch_inventory_equipment(self, user_id: str) -> dict | None:
        """Return {"inventory": {slot: [items]}, "rarity_breakdown": {...}}"""
        import market as mkt

        from services.spy.inventory_engine import (
            _SCRAP_MAP,
            _make_item,
            _remove_item,
            _remove_worst_by_rarity,
        )

        try:
            sync_result = await mkt.sync_user_tx_incremental(self._session, user_id)
            capped = sync_result.get("capped", False)
        except Exception as exc:
            log.error(f"_fetch_inventory_equipment: sync_user_tx_incremental gagal — {exc!r}")
            capped = False

        all_tx = await mkt.get_user_tx_cache(user_id, tx_type=None)
        pages = 0

        if not all_tx:
            return None

        all_tx.sort(key=lambda x: x.get("createdAt") or "")

        inventory: dict[str, list[dict]] = defaultdict(list)

        for tx in all_tx:
            tipe = tx.get("transactionType", "")
            raw = tx.get("item")
            if not raw:
                continue

            item = _make_item(raw)
            masuk = False

            if tipe in ("craftItem", "battleLoot", "openCase"):
                masuk = True
            elif tipe == "itemMarket":
                if tx.get("buyerId") == user_id:
                    masuk = True
                elif tx.get("sellerId") == user_id:
                    _remove_item(inventory, item, is_dismantle=False)
            elif tipe == "trading":
                if tx.get("buyerId") == user_id:
                    masuk = True
                elif tx.get("sellerId") == user_id:
                    _remove_item(inventory, item, is_dismantle=False)
            elif item["code"].lower() == "scrap":
                scrap_amount = raw.get("amount") or raw.get("quantity") or raw.get("scrapAmount") or 0
                if isinstance(scrap_amount, str):
                    try:
                        scrap_amount = int(scrap_amount)
                    except ValueError:
                        scrap_amount = 0
                for rarity_guess in _SCRAP_MAP.get(scrap_amount, []):
                    if _remove_worst_by_rarity(inventory, rarity_guess):
                        break
            elif tipe == "dismantleItem":
                _remove_item(inventory, item, is_dismantle=True)

            if masuk:
                inventory[item["slot"]].append(item)

        rarity_breakdown: dict[str, int] = defaultdict(int)
        total_items = 0
        for slot, daftar in inventory.items():
            for it in daftar:
                rarity_breakdown[it["rarity"]] += 1
                total_items += 1

        return {
            "inventory": dict(inventory),
            "rarity_breakdown": dict(rarity_breakdown),
            "total_items": total_items,
            "pages_fetched": pages,
            "capped": capped,
        }

    # --- inventory cache (app_db, TTL 6 jam) ---

    async def _get_cached_inventory(self, user_id: str) -> dict | None:
        """Ambil inventory dari cache kalau masih fresh, None kalau expired."""
        from services.spy import cache_store as spy_store
        try:
            row = await asyncio.to_thread(spy_store.get_cached_inventory, user_id)
        except Exception as exc:
            log.error(f"_get_cached_inventory({user_id}): {exc}")
            return None

        if not row:
            return None

        refreshed_at = row.get("refreshed_at")
        if not refreshed_at:
            return None
        try:
            refreshed_dt = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
        except Exception:
            return None

        age_hours = (datetime.now(timezone.utc) - refreshed_dt).total_seconds() / 3600
        if age_hours >= self.INVENTORY_CACHE_TTL_HOURS:
            return None

        return {
            "inventory": row.get("inventory") or {},
            "rarity_breakdown": row.get("rarity_breakdown") or {},
            "total_items": row.get("total_items") or 0,
            "pages_fetched": row.get("pages_fetched") or 0,
            "capped": bool(row.get("capped")),
            "refreshed_at": refreshed_at,
            "from_cache": True,
        }

    async def _refresh_inventory_cache(self, user_id: str) -> dict | None:
        """Fetch fresh, simpan ke cache, return shape sama kayak _get_cached_inventory."""
        result = await self._fetch_inventory_equipment(user_id)
        if result is None:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        capped = result.get("capped", False)

        row = {
            "inventory": result["inventory"],
            "rarity_breakdown": result["rarity_breakdown"],
            "total_items": result["total_items"],
            "pages_fetched": result["pages_fetched"],
            "capped": capped,
        }
        from services.spy import cache_store as spy_store
        try:
            await asyncio.to_thread(spy_store.upsert_inventory_cache, user_id, row)
        except Exception as exc:
            log.error(f"_refresh_inventory_cache upsert({user_id}): {exc}", exc_info=True)

        return {
            "inventory": result["inventory"],
            "rarity_breakdown": result["rarity_breakdown"],
            "total_items": result["total_items"],
            "pages_fetched": result["pages_fetched"],
            "capped": capped,
            "refreshed_at": now_iso,
            "from_cache": False,
        }

    async def _get_inventory(self, user_id: str) -> dict | None:
        """Entry point: cache-first, refresh-on-expire."""
        cached = await self._get_cached_inventory(user_id)
        if cached is not None:
            return cached
        return await self._refresh_inventory_cache(user_id)
