"""market_snapshot.py -- satu sumber snapshot pasar (getPrices + orderbook).

Hanya mengimpor `market`. Tidak menyentuh cache/DB bot; pemanggil yang menyimpan.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timezone

import market as mkt

log = logging.getLogger("WarEraBot.snapshot")

SNAPSHOT_DEPTH_LEVELS = 3     # level teratas per sisi untuk bid_qty/ask_qty
SPREAD_MAX_RATIO      = 0.10  # (ask-bid)/mid di atas ini -> mid = None
ORDERBOOK_CONCURRENCY = 4
SNAPSHOT_TIMEOUT_S    = 120   # batas waktu total satu build snapshot
MID_COVERAGE_WARN     = 0.8   # peringatan kalau item ber-mid di bawah ini

_lock = asyncio.Lock()
_cache: dict | None = None


def _num(x) -> float | None:
    """float finite > 0, selain itu None. bool ditolak."""
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def _top_qty(levels) -> float | None:
    """Jumlah qty valid dari N level teratas; None kalau tidak ada yang valid."""
    if not isinstance(levels, list):
        return None
    total, seen = 0.0, False
    for lv in levels[:SNAPSHOT_DEPTH_LEVELS]:
        q = _num(lv.get("qty")) if isinstance(lv, dict) else None
        if q is not None:
            total += q
            seen = True
    return total if seen else None


def compute_row(price, ob) -> dict:
    """Murni, tanpa I/O. Selalu mengembalikan enam key yang sama."""
    row = {"price": _num(price), "bid": None, "ask": None,
           "mid": None, "bid_qty": None, "ask_qty": None}
    if not isinstance(ob, dict):
        return row
    bid = _num(ob.get("best_bid"))
    ask = _num(ob.get("best_ask"))
    row["bid"], row["ask"] = bid, ask
    row["bid_qty"] = _top_qty(ob.get("bids"))
    row["ask_qty"] = _top_qty(ob.get("asks"))
    if bid is not None and ask is not None and bid <= ask:
        mid = (bid + ask) / 2
        if (ask - bid) / mid <= SPREAD_MAX_RATIO:
            row["mid"] = mid
    return row


async def _build(session) -> dict | None:
    prices = await mkt.fetch_prices(session)
    if not prices:
        log.warning("snapshot: getPrices kosong, snapshot dibatalkan")
        return None

    sem = asyncio.Semaphore(ORDERBOOK_CONCURRENCY)

    async def _ob(label: str):
        async with sem:
            try:
                return await mkt.fetch_orderbook(session, label)
            except Exception as exc:
                log.warning(f"snapshot: orderbook {label} gagal: {exc!r}")
                return None

    labels = list(prices)
    obs = await asyncio.gather(*(_ob(lb) for lb in labels))
    orderbooks = dict(zip(labels, obs))
    rows = {lb: compute_row(prices[lb], orderbooks[lb]) for lb in labels}

    with_mid = sum(1 for r in rows.values() if r["mid"] is not None)
    msg = f"snapshot: {len(rows)} item, {with_mid} ber-mid"
    if with_mid < len(rows) * MID_COVERAGE_WARN:
        log.warning(msg + " (di bawah ambang)")
    else:
        log.info(msg)

    return {"ts": datetime.now(timezone.utc), "mono": time.monotonic(),
            "prices": prices, "rows": rows, "orderbooks": orderbooks}


def _fresh(max_age: float) -> bool:
    return _cache is not None and (time.monotonic() - _cache["mono"]) <= max_age


async def get_market_snapshot(session, max_age: float = 60.0, force: bool = False) -> dict | None:
    """Single-flight. None kalau getPrices gagal (pemanggil jangan tulis DB)."""
    global _cache
    t0 = time.monotonic()
    if not force and _fresh(max_age):
        return _cache
    async with _lock:
        if _cache is not None and _cache["mono"] >= t0:
            return _cache            # ada yang selesai refresh selagi kita menunggu
        if not force and _fresh(max_age):
            return _cache
        try:
            snap = await asyncio.wait_for(_build(session), timeout=SNAPSHOT_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.error(f"snapshot: build melewati {SNAPSHOT_TIMEOUT_S}s, dibatalkan")
            return None
        if snap is not None:
            _cache = snap
        return snap
