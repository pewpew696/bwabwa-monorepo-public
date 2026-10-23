"""Logika Market: daftar item, detail + chart, orderbook (live + cache)."""
from datetime import datetime, timezone

import aiohttp

from market.prices import fetch_orderbook
from services.economy.items import resolve_item
from webapp.core.errors import NotFoundError
from webapp.queries import queries_cache, queries_market

ORDERBOOK_TTL_SECONDS = 30

# Ambang jam → bin chart. Bin 0 = raw (tanpa agregasi).
BIN_TIERS = (
    (48, 0),
    (168, 1),
    (720, 6),
    (2160, 24),
)
DEFAULT_HOURS = 168
WARMUP_BARS = 50  # cukup untuk MA30 + MACD(35) + RSI14(14) = 49


def _choose_bin(hours: int) -> int:
    for max_hours, bin_hours in BIN_TIERS:
        if hours <= max_hours:
            return bin_hours
    return BIN_TIERS[-1][1]


def _price_map(rows: list[dict]) -> dict:
    return {row["item_name"]: row["price"] for row in rows}


def _iso(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def _iso_rows(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    return [{k: (_iso(v) if k in keys else v) for k, v in row.items()} for row in rows]


def _empty_indicators() -> dict:
    return {
        "available": False,
        "ma_fast": [], "ma_slow": [], "ema": [], "rsi": [],
        "boll_upper": [], "boll_lower": [], "macd": [], "macd_signal": [],
    }


def _tail(values: list, n: int) -> list:
    if n <= 0:
        return []
    if n >= len(values):
        return list(values)
    return list(values[-n:])


def _align_indicator(values: list[float | None], bars: list[dict]) -> list[dict]:
    return [{"t": bar["t"], "v": v} for bar, v in zip(bars, values)]


def _align_boll(upper: list[float | None], lower: list[float | None], bars: list[dict]) -> list[dict]:
    return [{"t": bar["t"], "upper": u, "lower": l}
            for bar, u, l in zip(bars, upper, lower)]


def _align_macd(macd: list[float | None], signal: list[float | None], bars: list[dict]) -> list[dict]:
    out = []
    for bar, m, sig in zip(bars, macd, signal):
        hist = (m - sig) if (m is not None and sig is not None) else None
        out.append({"t": bar["t"], "macd": m, "signal": sig, "hist": hist})
    return out


class MarketService:
    def __init__(self, market_queries, cache_queries) -> None:
        self._market = market_queries
        self._cache = cache_queries

    def list_items(self) -> list[dict]:
        return _iso_rows(self._market.get_items_latest(), ("recorded_at",))

    def resolve(self, raw_name: str) -> str:
        rows = self._market.get_items_latest()
        resolved = resolve_item(_price_map(rows), raw_name)
        if not resolved:
            raise NotFoundError(f"item tidak ditemukan: {raw_name}")
        return resolved

    def get_item_detail(self, raw_name: str, hours: int = DEFAULT_HOURS) -> dict:
        item_name = self.resolve(raw_name)
        bin_hours = _choose_bin(hours)
        if bin_hours == 0:
            series = self._market.get_item_history_raw(item_name, hours)
            for row in series:
                row["bin_start"] = row["recorded_at"]
            binned = False
            series = _iso_rows(series, ("recorded_at", "bin_start"))
        else:
            series = self._market.get_item_history_binned(item_name, hours, bin_hours)
            binned = True
            series = _iso_rows(series, ("bin_start",))
        hourly = self._market.get_item_hourly_volume(item_name, hours)
        hourly = _iso_rows(hourly, ("hour_start",))
        return {
            "item_name": item_name,
            "hours": hours,
            "bin_hours": bin_hours,
            "binned": binned,
            "series": series,
            "hourly_volume": hourly,
        }

    def compute_indicators(self, raw_name: str, hours: int = DEFAULT_HOURS) -> dict:
        from webapp.web_services.indicator_service import compute_indicators

        item_name = self.resolve(raw_name)
        rows = self._market.get_item_history_raw(item_name, hours)
        prices = [float(r["price"]) for r in rows if r.get("price") is not None]
        bundle = compute_indicators(prices)
        if not bundle.available:
            return _empty_indicators()
        return {
            "available": True,
            "ma_fast": bundle.ma_fast, "ma_slow": bundle.ma_slow, "ema": bundle.ema,
            "rsi": bundle.rsi, "boll_upper": bundle.boll_upper, "boll_lower": bundle.boll_lower,
            "macd": bundle.macd, "macd_signal": bundle.macd_signal,
        }

    def get_item_ohlc_bundle(
        self,
        raw_name: str,
        hours: int = DEFAULT_HOURS,
        bin_hours_override: int | None = None,
    ) -> dict:
        from webapp.web_services.indicator_service import compute_indicators

        item_name = self.resolve(raw_name)
        bin_hours = bin_hours_override if bin_hours_override is not None else _choose_bin(hours)

        if bin_hours == 0:
            # Raw (tick): tanpa warmup — densitas tidak deterministik.
            rows = self._market.get_item_history_raw(item_name, hours)
            bars = [
                {
                    "t": int(r["recorded_at"].timestamp()),
                    "o": float(r["price"]),
                    "h": float(r["price"]),
                    "l": float(r["price"]),
                    "c": float(r["price"]),
                    "v": float(r["volume"]) if r.get("volume") is not None else 0.0,
                }
                for r in rows
                if r.get("price") is not None
            ]
            closes = [bar["c"] for bar in bars]
            bundle = compute_indicators(closes)
            indicators = {
                "available": bundle.available,
                "ma7":   _align_indicator(bundle.ma_fast, bars),
                "ma30":  _align_indicator(bundle.ma_slow, bars),
                "ema13": _align_indicator(bundle.ema, bars),
                "boll":  _align_boll(bundle.boll_upper, bundle.boll_lower, bars),
                "rsi14": _align_indicator(bundle.rsi, bars),
                "macd":  _align_macd(bundle.macd, bundle.macd_signal, bars),
            }
            return {
                "item_name": item_name,
                "range_hours": hours,
                "bin_hours": bin_hours,
                "bars": bars,
                "indicators": indicators,
            }

        # Binned: fetch WARMUP_BARS ekstra di kiri, hitung indikator dari
        # series penuh, lalu slice N bar terakhir supaya indikator "panas"
        # sejak bar pertama area yang ditampilkan.
        fetch_hours = hours + WARMUP_BARS * bin_hours
        rows = self._market.get_item_history_ohlc(item_name, fetch_hours, bin_hours)
        full_bars = [
            {
                "t": int(r["bin_start"].timestamp()),
                "o": float(r["open"]),
                "h": float(r["high"]),
                "l": float(r["low"]),
                "c": float(r["close"]),
                "v": float(r["volume"]) if r.get("volume") is not None else 0.0,
            }
            for r in rows
        ]

        closes_full = [bar["c"] for bar in full_bars]
        bundle_full = compute_indicators(closes_full)

        target_n = max(1, hours // bin_hours)
        n = min(target_n, len(full_bars))
        bars = full_bars[-n:] if n > 0 else []

        indicators = {
            "available": bundle_full.available,
            "ma7":   _align_indicator(_tail(bundle_full.ma_fast, n), bars),
            "ma30":  _align_indicator(_tail(bundle_full.ma_slow, n), bars),
            "ema13": _align_indicator(_tail(bundle_full.ema, n), bars),
            "boll":  _align_boll(
                _tail(bundle_full.boll_upper, n),
                _tail(bundle_full.boll_lower, n),
                bars,
            ),
            "rsi14": _align_indicator(_tail(bundle_full.rsi, n), bars),
            "macd":  _align_macd(
                _tail(bundle_full.macd, n),
                _tail(bundle_full.macd_signal, n),
                bars,
            ),
        }

        return {
            "item_name": item_name,
            "range_hours": hours,
            "bin_hours": bin_hours,
            "bars": bars,
            "indicators": indicators,
        }

    def get_item_ohlc_basic(
        self,
        raw_name: str,
        hours: int = DEFAULT_HOURS,
        bin_hours_override: int | None = None,
    ) -> dict:
        item_name = self.resolve(raw_name)
        bin_hours = bin_hours_override if bin_hours_override is not None else _choose_bin(hours)

        if bin_hours == 0:
            rows = self._market.get_item_history_raw(item_name, hours)
            bars = [
                {
                    "t": int(r["recorded_at"].timestamp()),
                    "o": float(r["price"]),
                    "h": float(r["price"]),
                    "l": float(r["price"]),
                    "c": float(r["price"]),
                    "v": float(r["volume"]) if r.get("volume") is not None else 0.0,
                }
                for r in rows
                if r.get("price") is not None
            ]
        else:
            rows = self._market.get_item_history_ohlc(item_name, hours, bin_hours)
            bars = [
                {
                    "t": int(r["bin_start"].timestamp()),
                    "o": float(r["open"]),
                    "h": float(r["high"]),
                    "l": float(r["low"]),
                    "c": float(r["close"]),
                    "v": float(r["volume"]) if r.get("volume") is not None else 0.0,
                }
                for r in rows
            ]

        return {
            "item_name": item_name,
            "range_hours": hours,
            "bin_hours": bin_hours,
            "bars": bars,
        }

    def get_orderbook_cached(self, raw_name: str) -> dict | None:
        item_name = self.resolve(raw_name)
        cached = self._cache.get_cache(f"orderbook:{item_name}")
        if cached is None or not self._cache.is_fresh(cached["fetched_at"], ORDERBOOK_TTL_SECONDS):
            return None
        return {"item_name": item_name, "orderbook": cached["data"], "fetched_at": cached["fetched_at"]}

    async def fetch_orderbook_live(self, raw_name: str) -> dict:
        item_name = self.resolve(raw_name)
        try:
            async with aiohttp.ClientSession() as session:
                orderbook = await fetch_orderbook(session, item_name)
        except Exception:
            orderbook = None
        if orderbook is not None:
            self._cache.set_cache(f"orderbook:{item_name}", orderbook)
        return {
            "item_name": item_name,
            "orderbook": orderbook,
            "fetched_at": datetime.now(timezone.utc),
        }
