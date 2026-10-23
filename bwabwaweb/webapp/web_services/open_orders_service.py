"""Logika Open Orders: scan semua item untuk cari order aktif 1 user."""
import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

import market
from services.economy.constants import ITEM_LABELS
from services.spy.search import find_player_exact
from services.spy.utils import not_found_msg
from webapp.core.errors import NotFoundError

CACHE_TTL_SECONDS = 300.0
_cache: dict = {}

log = logging.getLogger("WarEraBot.webapp.open_orders")


@dataclass(frozen=True)
class OpenOrderEntry:
    item_name: str
    side: str
    price: float
    qty: int


@dataclass(frozen=True)
class OpenOrdersReport:
    user_id: str
    username: str
    orders: list[OpenOrderEntry]


class OpenOrdersService:
    async def get_open_orders(self, raw_name: str) -> OpenOrdersReport:
        cache_key = (raw_name or "").strip().lower()
        now_mono = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and (now_mono - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        async with aiohttp.ClientSession() as session:
            data, suggestions = await find_player_exact(session, raw_name)
            if not data:
                raise NotFoundError(not_found_msg("Player", raw_name, suggestions))

            user_id = data["_id"]
            username = data.get("username", raw_name)

            item_names = list(set(ITEM_LABELS.values()))
            sem = asyncio.Semaphore(10)

            async def fetch_item(item_name: str) -> list[OpenOrderEntry]:
                async with sem:
                    try:
                        ob = await market.fetch_orderbook(session, item_name)
                        if not ob:
                            return []
                        found: list[OpenOrderEntry] = []
                        for o in ob.get("raw_buys", []):
                            if o.get("user") == user_id:
                                found.append(OpenOrderEntry(
                                    item_name=item_name,
                                    side="BUY",
                                    price=float(o.get("price", 0)),
                                    qty=int(float(o.get("quantity", 0))),
                                ))
                        for o in ob.get("raw_sells", []):
                            if o.get("user") == user_id:
                                found.append(OpenOrderEntry(
                                    item_name=item_name,
                                    side="SELL",
                                    price=float(o.get("price", 0)),
                                    qty=int(float(o.get("quantity", 0))),
                                ))
                        return found
                    except Exception as exc:
                        log.warning(f"fetch_item({item_name}) gagal: {exc!r}")
                        return []

            results = await asyncio.gather(*[fetch_item(i) for i in item_names])
            all_orders: list[OpenOrderEntry] = []
            for r in results:
                all_orders.extend(r)

            all_orders.sort(key=lambda x: (x.item_name, x.side == "SELL"))

            report = OpenOrdersReport(user_id=user_id, username=username, orders=all_orders)
            _cache[cache_key] = (time.monotonic(), report)
            return report
