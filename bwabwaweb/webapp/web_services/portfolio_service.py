"""Logika Portfolio: port dari web_api/hub_intel.py::hub_user_portfolio.

aiohttp.ClientSession baru per request. Fungsi market/ dan services/spy/
dipakai apa adanya — sync cache incremental + baca cache, bukan live fetch.
"""
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp

import market
from services.spy.api_client import get_user_lite
from services.spy.resolve import resolve_country_name
from services.spy.search import find_player_exact
from services.spy.utils import not_found_msg
from webapp.core.errors import NotFoundError
from webapp.web_services.hub_intel_helpers import _clean_and_sort

CACHE_TTL_SECONDS = 300.0
_cache: dict = {}

log = logging.getLogger("WarEraBot.portfolio")

DEFAULT_DAYS = 20


def _new_country_rec():
    return {"profit": 0.0, "volume": 0.0, "tx_count": 0, "wins": 0, "losses": 0,
            "biggest_loss": 0.0, "buy_cost": 0.0}


@dataclass(frozen=True)
class CitizenshipEntry:
    country_id: str
    country_name: str
    tx_count: int
    first_seen: str
    last_seen: str


@dataclass(frozen=True)
class CountryStat:
    country_id: str | None
    country_name: str
    profit: float
    roi_pct: float
    volume: float
    win_rate_pct: float
    wins: int
    losses: int
    tx_count: int
    biggest_loss: float
    date_range: list | None


@dataclass(frozen=True)
class PortfolioTotal:
    profit: float
    roi_pct: float
    volume: float
    win_rate_pct: float
    wins: int
    losses: int
    tx_count: int
    biggest_loss: float


@dataclass(frozen=True)
class PortfolioReport:
    user_id: str
    username: str
    all_history: bool
    days: int
    citizenship_history: list[CitizenshipEntry]
    per_country: list[CountryStat]
    total: PortfolioTotal


class PortfolioService:
    async def get_portfolio(
        self,
        raw_name: str,
        all_history: bool = False,
        days: int = DEFAULT_DAYS,
    ) -> PortfolioReport:
        q = raw_name.strip()

        cache_key = (q.lower(), all_history, days)
        now_mono = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and (now_mono - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        since_dt = None if all_history else (datetime.now(timezone.utc) - timedelta(days=days))
        not_found_hint: list[str] = []

        async with aiohttp.ClientSession() as session:
            if not (len(q) == 24 and all(c in "0123456789abcdef" for c in q)):
                found, suggestions = await find_player_exact(session, q)
                if not found:
                    not_found_hint.extend(suggestions)
                    raise NotFoundError(not_found_msg("Player", q, not_found_hint))
                user_id = found["_id"]
            else:
                user_id = q

            try:
                await market.sync_user_tx_incremental(
                    session, user_id, headers=market._hub_auth_headers()
                )
            except Exception as exc:
                log.error(f"sync_user_tx_incremental({user_id}) gagal: {exc!r}")

            raw_tx = await market.get_user_tx_cache(user_id, tx_type=None)
            all_tx = _clean_and_sort(raw_tx, since_dt)

            buys = defaultdict(deque)
            per_country = defaultdict(_new_country_rec)
            countries_seen: dict = {}
            date_range: dict = {}
            total = _new_country_rec()

            for tx in all_tx:
                item_code = tx["itemCode"]
                qty = float(tx["quantity"])
                money = float(tx.get("money") or 0)
                price = money / qty if qty else 0.0
                dt = tx["_dt"]

                is_buyer = tx.get("buyerId") == user_id
                is_seller = tx.get("sellerId") == user_id
                country_tag = tx.get("buyerCountryId") if is_buyer else tx.get("sellerCountryId")
                ckey = country_tag or "(tanpa negara)"

                if country_tag:
                    first, last, cnt = countries_seen.get(country_tag, (dt, dt, 0))
                    countries_seen[country_tag] = (min(first, dt), max(last, dt), cnt + 1)

                first_b, last_b = date_range.get(ckey, (dt, dt))
                date_range[ckey] = (min(first_b, dt), max(last_b, dt))

                if is_buyer:
                    buys[item_code].append([qty, price, dt])
                    per_country[ckey]["tx_count"] += 1
                    per_country[ckey]["volume"] += money
                    per_country[ckey]["buy_cost"] += money
                    total["tx_count"] += 1
                    total["volume"] += money
                    total["buy_cost"] += money

                if is_seller:
                    per_country[ckey]["tx_count"] += 1
                    per_country[ckey]["volume"] += money
                    total["tx_count"] += 1
                    total["volume"] += money

                    queue = buys.get(item_code)
                    if queue:
                        remaining = qty
                        while remaining > 1e-9 and queue:
                            batch_qty, batch_price, _ = queue[0]
                            take = min(batch_qty, remaining)
                            remaining -= take
                            batch_qty -= take
                            pnl = take * (price - batch_price)

                            per_country[ckey]["profit"] += pnl
                            total["profit"] += pnl
                            if pnl > 1e-9:
                                per_country[ckey]["wins"] += 1
                                total["wins"] += 1
                            elif pnl < -1e-9:
                                per_country[ckey]["losses"] += 1
                                total["losses"] += 1
                                per_country[ckey]["biggest_loss"] = min(per_country[ckey]["biggest_loss"], pnl)
                                total["biggest_loss"] = min(total["biggest_loss"], pnl)

                            if batch_qty <= 1e-9:
                                queue.popleft()
                            else:
                                queue[0][0] = batch_qty

            username = user_id[:8] + "..."
            try:
                data = await get_user_lite(session, user_id)
                if data:
                    username = data.get("username") or username
            except Exception:
                pass

            citizenship_history = []
            for cid, (first, last, cnt) in sorted(countries_seen.items(), key=lambda kv: -kv[1][2]):
                cname = cid
                try:
                    cname = await resolve_country_name(session, cid)
                except Exception:
                    pass
                citizenship_history.append(CitizenshipEntry(
                    country_id=cid,
                    country_name=cname,
                    tx_count=cnt,
                    first_seen=first.strftime("%Y-%m-%d"),
                    last_seen=last.strftime("%Y-%m-%d"),
                ))

            per_country_out = []
            for ckey, rec in sorted(per_country.items(), key=lambda kv: -kv[1]["profit"]):
                if ckey == "(tanpa negara)":
                    cname = ckey
                else:
                    try:
                        cname = await resolve_country_name(session, ckey)
                    except Exception:
                        cname = ckey[:8] + "..."

                roi = (rec["profit"] / rec["buy_cost"] * 100) if rec["buy_cost"] else 0.0
                decided = rec["wins"] + rec["losses"]
                win_rate = (rec["wins"] / decided * 100) if decided else 0.0
                fb, lb = date_range.get(ckey, (None, None))
                date_range_out = [fb.strftime("%Y-%m-%d"), lb.strftime("%Y-%m-%d")] if fb else None

                per_country_out.append(CountryStat(
                    country_id=None if ckey == "(tanpa negara)" else ckey,
                    country_name=cname,
                    profit=round(rec["profit"], 4),
                    roi_pct=round(roi, 2),
                    volume=round(rec["volume"], 2),
                    win_rate_pct=round(win_rate, 1),
                    wins=rec["wins"],
                    losses=rec["losses"],
                    tx_count=rec["tx_count"],
                    biggest_loss=round(rec["biggest_loss"], 4),
                    date_range=date_range_out,
                ))

            roi_total = (total["profit"] / total["buy_cost"] * 100) if total["buy_cost"] else 0.0
            decided_total = total["wins"] + total["losses"]
            win_rate_total = (total["wins"] / decided_total * 100) if decided_total else 0.0

            total_out = PortfolioTotal(
                profit=round(total["profit"], 4),
                roi_pct=round(roi_total, 2),
                volume=round(total["volume"], 2),
                win_rate_pct=round(win_rate_total, 1),
                wins=total["wins"],
                losses=total["losses"],
                tx_count=total["tx_count"],
                biggest_loss=round(total["biggest_loss"], 4),
            )

            report = PortfolioReport(
                user_id=user_id,
                username=username,
                all_history=all_history,
                days=days,
                citizenship_history=citizenship_history,
                per_country=per_country_out,
                total=total_out,
            )
            _cache[cache_key] = (time.monotonic(), report)
            return report
