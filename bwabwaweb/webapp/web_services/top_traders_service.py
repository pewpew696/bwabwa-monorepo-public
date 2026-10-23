"""Logika Top Traders: leaderboard trader per negara dari tx API.

Port dari web_api/hub_intel.py::hub_top_traders.
aiohttp.ClientSession baru per request. Fungsi market/ dan services/spy/
dipakai apa adanya.
"""
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

import market
from services.spy.api_client import get_user_lite
from webapp.core.errors import NotFoundError
from webapp.web_services.hub_intel_helpers import (
    TX_MAX_PAGES_USER,
    _clean_and_sort,
    _fetch_transactions,
)

log = logging.getLogger("WarEraBot.top_traders")

DEFAULT_DAYS = 20
DEFAULT_MIN_TX = 20
TOP_N = 5
CACHE_TTL_SECONDS = 300.0

_cache: dict = {}


@dataclass(frozen=True)
class TopTraderRow:
    rank: int
    user_id: str
    username: str
    profit: float
    roi_pct: float
    volume: float
    win_rate_pct: float
    wins: int
    losses: int
    tx_count: int
    biggest_loss: float


@dataclass(frozen=True)
class TopTradersReport:
    country_id: str
    country_name: str
    days: int
    min_tx: int
    traders: list[TopTraderRow]


def _new_trader_rec():
    return {"buys": defaultdict(deque), "profit": 0.0, "tx_count": 0,
            "buy_cost": 0.0, "volume": 0.0, "wins": 0, "losses": 0,
            "biggest_loss": 0.0}


class TopTradersService:
    async def get_top_traders(
        self,
        q: str,
        days: int = DEFAULT_DAYS,
        min_tx: int = DEFAULT_MIN_TX,
    ) -> TopTradersReport:
        q = q.strip()
        if not q:
            raise NotFoundError("Missing param 'q' (nama atau ID negara)")

        cache_key = (q.lower(), days, min_tx)
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
                max_pages=TX_MAX_PAGES_USER,
            )
            all_tx = _clean_and_sort(raw_tx, since_dt)

            per_user: dict = defaultdict(_new_trader_rec)

            for tx in all_tx:
                item_code = tx["itemCode"]
                qty = float(tx["quantity"])
                money = float(tx.get("money") or 0)
                price = money / qty if qty else 0.0

                if tx.get("buyerCountryId") == country_id and tx.get("buyerId"):
                    rec = per_user[tx["buyerId"]]
                    rec["tx_count"] += 1
                    rec["buy_cost"] += money
                    rec["volume"] += money
                    rec["buys"][item_code].append([qty, price, tx["_dt"]])

                if tx.get("sellerCountryId") == country_id and tx.get("sellerId"):
                    rec = per_user[tx["sellerId"]]
                    rec["tx_count"] += 1
                    rec["volume"] += money
                    queue = rec["buys"].get(item_code)
                    if queue:
                        remaining = qty
                        while remaining > 1e-9 and queue:
                            batch_qty, batch_price, _ = queue[0]
                            take = min(batch_qty, remaining)
                            remaining -= take
                            batch_qty -= take
                            trade_pnl = take * (price - batch_price)
                            rec["profit"] += trade_pnl
                            if trade_pnl > 1e-9:
                                rec["wins"] += 1
                            elif trade_pnl < -1e-9:
                                rec["losses"] += 1
                                rec["biggest_loss"] = min(rec["biggest_loss"], trade_pnl)
                            if batch_qty <= 1e-9:
                                queue.popleft()
                            else:
                                queue[0][0] = batch_qty

            qualified = [(uid, rec) for uid, rec in per_user.items() if rec["tx_count"] >= min_tx]
            qualified.sort(key=lambda kv: -kv[1]["profit"])
            top = qualified[:TOP_N]

            traders = []
            for rank, (uid, rec) in enumerate(top, start=1):
                username = uid[:8] + "..."
                try:
                    data = await get_user_lite(session, uid)
                    if data:
                        username = data.get("username") or username
                except Exception:
                    pass

                roi = (rec["profit"] / rec["buy_cost"] * 100) if rec["buy_cost"] else 0.0
                decided = rec["wins"] + rec["losses"]
                win_rate = (rec["wins"] / decided * 100) if decided else 0.0

                traders.append(TopTraderRow(
                    rank=rank,
                    user_id=uid,
                    username=username,
                    profit=round(rec["profit"], 4),
                    roi_pct=round(roi, 2),
                    volume=round(rec["volume"], 2),
                    win_rate_pct=round(win_rate, 1),
                    wins=rec["wins"],
                    losses=rec["losses"],
                    tx_count=rec["tx_count"],
                    biggest_loss=round(rec["biggest_loss"], 4),
                ))

            report = TopTradersReport(
                country_id=country_id,
                country_name=country_name,
                days=days,
                min_tx=min_tx,
                traders=traders,
            )
            _cache[cache_key] = (time.monotonic(), report)
            return report
