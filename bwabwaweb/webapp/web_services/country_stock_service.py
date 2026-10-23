"""Logika Country Stock: open stock + tx log negara dari tx API.

Port dari web_api/hub_intel.py::hub_country_stock.
aiohttp.ClientSession baru per request. Helper dari hub_intel_helpers.
"""
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

import market
from webapp.core.errors import NotFoundError
from webapp.web_services.hub_intel_helpers import (
    TX_MAX_PAGES_COUNTRY,
    _clean_and_sort,
    _fetch_transactions,
)

log = logging.getLogger("WarEraBot.country_stock")

DEFAULT_DAYS = 20
CACHE_TTL_SECONDS = 300.0

_cache: dict = {}


@dataclass(frozen=True)
class TxEntry:
    dt: datetime
    side: str
    item: str
    qty: float
    price: float


@dataclass(frozen=True)
class StockEntry:
    item: str
    qty: float
    avg_buy_price: float
    oldest_batch: datetime


@dataclass(frozen=True)
class CountryStockReport:
    country_id: str
    country_name: str
    days: int
    transactions: list[TxEntry]
    open_stock: list[StockEntry]


class CountryStockService:
    async def get_country_stock(self, q: str, days: int = DEFAULT_DAYS) -> CountryStockReport:
        q = q.strip()
        if not q:
            raise NotFoundError("Missing param 'q' (nama atau ID negara)")

        cache_key = (q.lower(), days)
        now_mono = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and (now_mono - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        since_dt = datetime.now(timezone.utc) - timedelta(days=days)

        async with aiohttp.ClientSession() as session:
            resolved = await market.fetch_country_id_by_name(session, q, with_cache=True)
            if not resolved:
                raise NotFoundError(f"Negara '{q}' tidak ditemukan")
            country_id, country_name = resolved

            raw_tx = await _fetch_transactions(
                session, country_id=country_id, since_dt=since_dt,
                max_pages=TX_MAX_PAGES_COUNTRY,
            )
            all_tx = _clean_and_sort(raw_tx, since_dt)

            open_buys: dict = {}
            tx_log: list = []

            for tx in all_tx:
                item_code = tx["itemCode"]
                qty = float(tx["quantity"])
                money = float(tx.get("money") or 0)
                price = money / qty if qty else 0.0
                dt = tx["_dt"]

                is_buy = tx.get("buyerCountryId") == country_id
                is_sell = tx.get("sellerCountryId") == country_id

                if is_buy or is_sell:
                    tx_log.append(TxEntry(
                        dt=dt,
                        side="BUY" if is_buy else "SELL",
                        item=market.ITEM_LABELS.get(item_code, item_code),
                        qty=qty,
                        price=round(price, 4),
                    ))

                if is_buy:
                    open_buys.setdefault(item_code, deque()).append([qty, price, dt])
                elif is_sell:
                    queue = open_buys.get(item_code)
                    if not queue:
                        continue
                    remaining = qty
                    while remaining > 1e-9 and queue:
                        batch_qty, batch_price, _ = queue[0]
                        take = min(batch_qty, remaining)
                        remaining -= take
                        batch_qty -= take
                        if batch_qty <= 1e-9:
                            queue.popleft()
                        else:
                            queue[0][0] = batch_qty

            open_stock = []
            for item_code, queue in open_buys.items():
                remaining_qty = sum(b[0] for b in queue)
                if remaining_qty <= 1e-9:
                    continue
                total_cost = sum(b[0] * b[1] for b in queue)
                avg_price = total_cost / remaining_qty
                oldest_dt = min(b[2] for b in queue)
                open_stock.append(StockEntry(
                    item=market.ITEM_LABELS.get(item_code, item_code),
                    qty=round(remaining_qty, 4),
                    avg_buy_price=round(avg_price, 4),
                    oldest_batch=oldest_dt,
                ))
            open_stock.sort(key=lambda r: -r.qty)
            tx_log.sort(key=lambda r: r.dt, reverse=True)

            report = CountryStockReport(
                country_id=country_id,
                country_name=country_name,
                days=days,
                transactions=tx_log,
                open_stock=open_stock,
            )
            _cache[cache_key] = (time.monotonic(), report)
            return report
