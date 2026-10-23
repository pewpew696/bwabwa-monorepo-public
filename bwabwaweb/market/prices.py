# market/prices.py — fetch harga, orderbook, volume, top movers
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from services.db import pool as db_pool

from .auth import HEADERS, _auth_headers
from .client import _encode, _get_json_with_retry
from .constants import (
    BASE_URL,
    ITEM_LABELS,
    ITEM_LABEL_TO_CODE,
    ORDERS_URL,
    PRICES_URL,
    TRANSACTION_URL,
)
from .items import (
    _api_key_from_item_id,
    _item_id_from_api_key,
    _label,
    _resolve_item_id,
)
from .rate_limit import _bf_time

log = logging.getLogger("WarEraBot.market")


ORDERBOOK_DEPTH  = 100


async def fetch_prices(session: aiohttp.ClientSession) -> dict[str, float]:
    try:
        resp = await _get_json_with_retry(session, PRICES_URL, headers=HEADERS, timeout=10)
        raw: dict = resp["result"]["data"]
        out = {}
        for k, v in raw.items():
            item_id = _item_id_from_api_key(k)
            if item_id not in ITEM_LABELS:
                continue
            out[_label(item_id)] = round(float(v), 6)
        return out
    except Exception as exc:
        log.error(f"fetch_prices: {type(exc).__name__}: {exc!r}")
        return {}


async def fetch_orderbook(session: aiohttp.ClientSession, item_name: str) -> dict | None:
    item_id = _resolve_item_id(item_name)
    if item_id is None:
        return None
    api_key = _api_key_from_item_id(item_id)
    if api_key is None:
        return None
    try:
        url  = f"{ORDERS_URL}?input={_encode({'itemCode': api_key, 'limit': ORDERBOOK_DEPTH})}"
        resp = await _get_json_with_retry(session, url, headers=HEADERS, timeout=10)
        data = resp["result"]["data"]
        raw_buys  = data.get("buyOrders", [])
        raw_sells = data.get("sellOrders", [])

        def _build(orders: list, descending: bool) -> list[dict]:
            sorted_orders = sorted(orders, key=lambda o: float(o.get("price", 0)), reverse=descending)
            aggregated = []
            for o in sorted_orders:
                price = round(float(o.get("price", 0)), 6)
                qty   = int(o.get("quantity", 0))
                if aggregated and aggregated[-1]["price"] == price:
                    aggregated[-1]["qty"]   += qty
                    aggregated[-1]["count"] += 1
                else:
                    aggregated.append({"price": price, "qty": qty, "count": 1})
            result, cum = [], 0
            for a in aggregated:
                cum += a["qty"]
                result.append({"price": a["price"], "qty": a["qty"], "cumQty": cum, "count": a["count"]})
            return result

        bids = _build(raw_buys, descending=True)
        asks = _build(raw_sells, descending=False)
        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None
        spread   = round(best_ask - best_bid, 6) if (best_bid is not None and best_ask is not None) else None

        return {
            "item": _label(item_id), "bids": bids, "asks": asks,
            "best_bid": best_bid, "best_ask": best_ask, "spread": spread,
            "buy_vol": sum(o["qty"] for o in bids), "sell_vol": sum(o["qty"] for o in asks),
            "raw_buys": raw_buys, "raw_sells": raw_sells,
        }
    except Exception as exc:
        log.error(f"fetch_orderbook({item_name}): {exc}")
        return None


async def fetch_all_spreads(session: aiohttp.ClientSession) -> list[dict]:
    async def _get_spread(item_id: str) -> dict | None:
        api_key = _api_key_from_item_id(item_id)
        if api_key is None:
            return None
        try:
            url  = f"{ORDERS_URL}?input={_encode({'itemCode': api_key})}"
            resp = await _get_json_with_retry(session, url, headers=HEADERS, timeout=15)
            data = resp["result"]["data"]
            raw_buys  = data.get("buyOrders", [])
            raw_sells = data.get("sellOrders", [])
            best_bid = max((float(o.get("price", 0)) for o in raw_buys),  default=None)
            best_ask = min((float(o.get("price", 0)) for o in raw_sells), default=None)
            if best_bid is not None:
                best_bid = round(best_bid, 6)
            if best_ask is not None:
                best_ask = round(best_ask, 6)
            spread = round(best_ask - best_bid, 6) if (best_bid is not None and best_ask is not None) else None
            return {"item": _label(item_id), "best_bid": best_bid, "best_ask": best_ask, "spread": spread}
        except Exception as exc:
            log.warning(f"fetch_all_spreads [{item_id}]: {exc}")
            return None

    tasks   = [_get_spread(item_id) for item_id in ITEM_LABELS]
    results = await asyncio.gather(*tasks)
    out     = [r for r in results if r is not None]
    out.sort(key=lambda x: (x["spread"] is None, x["spread"] or 0))
    return out


async def fetch_volume_24h(session: aiohttp.ClientSession) -> dict[str, dict]:
    """Volume transaksi 24 jam terakhir buat semua item, dipake xmarket
    halaman 2. Return {item_label: {"tx", "qty", "qty_h"}}."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat().replace("+00:00", "Z")

    async def _fetch_item(item_code: str, item_label: str) -> tuple[str, dict]:
        tx_count  = 0
        qty_total = 0
        cursor    = None

        for _ in range(50):
            params: dict = {"itemCode": item_code, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            url = f"{TRANSACTION_URL}?input={_encode(params)}"
            try:
                raw = await _get_json_with_retry(session, url, headers=_auth_headers(), timeout=15)
                if isinstance(raw, list):
                    data = raw[0].get("result", {}).get("data", {}) if raw else {}
                else:
                    data = raw.get("result", {}).get("data", {})
            except Exception as exc:
                log.warning(f"fetch_volume_24h [{item_label}]: {exc}")
                break

            items       = data.get("items", [])
            next_cursor = data.get("nextCursor")

            stop = False
            for item in items:
                created = item.get("createdAt", "")
                if created < cutoff:
                    stop = True
                    break
                tx_count  += 1
                qty_total += int(item.get("quantity", 0) or 0)

            if stop or not next_cursor or not items:
                break
            cursor = next_cursor

        qty_h = round(qty_total / 24, 1)
        return item_label, {"tx": tx_count, "qty": qty_total, "qty_h": qty_h}

    sem = asyncio.Semaphore(5)

    async def _fetch_with_sem(code: str, label: str) -> tuple[str, dict]:
        async with sem:
            return await _fetch_item(code, label)

    tasks = [_fetch_with_sem(code, label) for label, code in ITEM_LABEL_TO_CODE.items()]
    results = await asyncio.gather(*tasks)
    return dict(results)


_VOLUME_BATCH_MAX_URL = 6000


def _parse_created_at(iso: str | None):
    """Parse createdAt ISO UTC -> datetime aware. None kalau gagal."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


async def fetch_volume_24h_batched(session: aiohttp.ClientSession) -> dict[str, dict]:
    """Versi batch dari fetch_volume_24h. Return {item_label: {"tx", "qty", "qty_h"}}."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    started = _bf_time.monotonic()
    req_count = 0
    state = {
        label: {"code": code, "cursor": None, "tx": 0, "qty": 0, "by_hour": {}}
        for label, code in ITEM_LABEL_TO_CODE.items()
    }

    async def _fetch_round(group: list[str]) -> dict[str, dict | None]:
        nonlocal req_count
        inputs = {}
        for i, label in enumerate(group):
            params: dict = {"itemCode": state[label]["code"], "limit": 100}
            if state[label]["cursor"]:
                params["cursor"] = state[label]["cursor"]
            inputs[str(i)] = params
        methods = ",".join(["transaction.getPaginatedTransactions"] * len(group))
        url = f"{BASE_URL}/{methods}?batch=1&input={_encode(inputs)}"
        if len(url) > _VOLUME_BATCH_MAX_URL and len(group) > 1:
            mid = len(group) // 2
            left = await _fetch_round(group[:mid])
            right = await _fetch_round(group[mid:])
            return {**left, **right}
        try:
            req_count += 1
            results = await _get_json_with_retry(session, url, headers=_auth_headers(), timeout=30)
        except Exception as exc:
            log.warning(f"fetch_volume_24h_batched: request gagal ({len(group)} item): {exc}")
            return {label: None for label in group}
        if not isinstance(results, list):
            return {label: None for label in group}
        out: dict[str, dict | None] = {}
        for i, label in enumerate(group):
            res = results[i] if i < len(results) else None
            if isinstance(res, dict) and "result" in res:
                out[label] = (res["result"] or {}).get("data") or {}
            else:
                out[label] = None
        return out

    active = list(state.keys())
    rounds = 0
    for _ in range(1000):  # safety net; exit utama = created < cutoff
        if not active:
            break
        rounds += 1
        data_by_label: dict[str, dict | None] = {}
        for start in range(0, len(active), 50):
            data_by_label.update(await _fetch_round(active[start:start + 50]))
        next_active = []
        for label in active:
            data = data_by_label.get(label)
            if data is None:
                log.warning(f"fetch_volume_24h_batched [{label}]: ronde {rounds} gagal, pakai hasil parsial")
                continue
            st = state[label]
            items = data.get("items", [])
            next_cursor = data.get("nextCursor")
            stop = False
            for item in items:
                created = item.get("createdAt", "")
                if created < cutoff:
                    stop = True
                    break
                st["tx"] += 1
                qty = int(item.get("quantity", 0) or 0)
                st["qty"] += qty
                if qty:
                    dt = _parse_created_at(created)
                    if dt is not None:
                        hour = dt.replace(minute=0, second=0, microsecond=0)
                        st["by_hour"][hour] = st["by_hour"].get(hour, 0) + qty
            if stop or not next_cursor or not items:
                continue
            st["cursor"] = next_cursor
            next_active.append(label)
        active = next_active

    result = {
        label: {
            "tx": st["tx"], "qty": st["qty"], "qty_h": round(st["qty"] / 24, 1),
            "by_hour": st["by_hour"],
        }
        for label, st in state.items()
    }
    log.info(
        f"fetch_volume_24h_batched: {req_count} request, {rounds} ronde, "
        f"{_bf_time.monotonic() - started:.1f}s"
    )
    return result


async def fetch_top_movers(hours: int = 24) -> dict[str, dict]:
    """Top gainer & loser dari histori harga di Supabase.
    Return: {"gainers": [...top 5], "losers": [...top 5], "hours": int}"""
    try:
        now    = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=hours)).isoformat()

        result = await asyncio.to_thread(
            lambda: (
                db_pool.table("price_history")
                .select("item_name, price, recorded_at")
                .gte("recorded_at", cutoff)
                .order("recorded_at", desc=False)
                .execute()
            )
        )
        rows = result or []
    except Exception as exc:
        log.error(f"fetch_top_movers: {exc}")
        return {"gainers": [], "losers": [], "hours": hours}

    from collections import defaultdict
    item_prices: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        item_prices[row["item_name"]].append((row["recorded_at"], row["price"]))

    movers = []
    for item, prices in item_prices.items():
        if len(prices) < 2:
            continue
        price_old = prices[0][1]
        price_new = prices[-1][1]
        if price_old == 0:
            continue
        pct = ((price_new - price_old) / price_old) * 100
        movers.append({"item": item, "change": pct, "price_old": price_old, "price_new": price_new})

    movers.sort(key=lambda m: m["change"], reverse=True)
    gainers = [m for m in movers if m["change"] > 0][:5]
    losers  = [m for m in reversed(movers) if m["change"] < 0][:5]

    return {"gainers": gainers, "losers": losers, "hours": hours}
