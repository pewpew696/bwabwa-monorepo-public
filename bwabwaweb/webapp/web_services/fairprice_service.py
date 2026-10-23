"""Logika Fairprice: analisis 1 item, live fetch + engine murni.

Port dari cogs/economy/fairprice.py::_fp_analyze + base.py::_fp_analyze_batch.
Manual overrides (cogs in-memory) sengaja SKIP — tidak ada di DB.
Cache in-memory TTL 5 menit per item. aiohttp.ClientSession per request.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import aiohttp

import market
from services.economy.constants import ITEM_LABELS, PRODUCTION_CHAIN
from services.economy.fairprice_cost import fp_compute_cost_engine
from services.economy.fairprice_engine import (
    fp_compute_confidence,
    fp_compute_fair_range,
    fp_compute_risk,
    fp_compute_technical_value,
    fp_compute_valuation,
    fp_decide_recommendation,
)
from services.economy.fairprice_liquidity import (
    fp_compute_data_confidence,
    fp_compute_liquidity_view,
)
from services.economy.fairprice_market import fp_parse_orderbook
from services.economy.fairprice_reason import (
    _fp_reason_key,
    fp_compute_reasons,
)
from services.economy.liquidity import (
    _anchor_age_days,
    _compute_liquidity_score,
)
from webapp.core.errors import NotFoundError
from webapp.queries import queries_fairprice

log = logging.getLogger("WarEraBot.fairprice")

CACHE_TTL_SECONDS = 300.0
TECHNICAL_WINDOW_DAYS = 7
TREND_WINDOW_HOURS = 720  # 30 hari
TREND_THRESHOLD_PCT = 3.0
LIQ_CUTOFF_DAYS = 7
LIQ_LOOKBACK_DAYS = 30


_cache: dict[str, tuple[float, dict]] = {}


def _valid_item_labels() -> set[str]:
    return set(ITEM_LABELS.values())


def _fetch_trend_30d(item: str) -> tuple[str, str]:
    """Port dari cogs/economy/fairprice.py::_fp_trend_30d.

    Sumber: tabel price_history via queries (live fetch tidak tersedia
    untuk history; ini satu-satunya sumber).
    """
    rows = queries_fairprice.get_price_history(item, hours=TREND_WINDOW_HOURS)
    if len(rows) < 2:
        return "⚪ Sideways (insufficient 30d data)", "Sideways"

    baseline = float(rows[0]["price"])
    current = float(rows[-1]["price"])
    if not baseline:
        return "⚪ Sideways (insufficient 30d data)", "Sideways"

    chg = (current - baseline) / baseline * 100
    if chg > TREND_THRESHOLD_PCT:
        return f"🟢 Bullish (30d {chg:+.1f}%)", "Bullish"
    if chg < -TREND_THRESHOLD_PCT:
        return f"🔴 Bearish (30d {chg:+.1f}%)", "Bearish"
    return f"⚪ Sideways (30d {chg:+.1f}%)", "Sideways"


def _make_get_bonus(auto_bonus: dict[str, float]):
    def _get_bonus(item: str) -> tuple[float, str]:
        for k, v in auto_bonus.items():
            if k.lower() == item.lower():
                return v, "auto"
        return 0.0, "none"
    return _get_bonus


def _make_get_median_bonus(median_bonus: dict[str, float]):
    def _get_median_bonus(item: str) -> tuple[float, str]:
        for k, v in median_bonus.items():
            if k.lower() == item.lower():
                return v, "median"
        return 0.0, "none"
    return _get_median_bonus


class FairpriceService:
    async def get_fairprice(self, item_label: str) -> dict:
        item_label = (item_label or "").strip()
        if not item_label:
            raise NotFoundError("Item kosong")
        if item_label not in _valid_item_labels():
            raise NotFoundError(f"Item '{item_label}' tidak dikenal")

        now_mono = time.monotonic()
        cached = _cache.get(item_label)
        if cached and (now_mono - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        result = await self._compute(item_label)
        _cache[item_label] = (time.monotonic(), result)
        return result

    async def _compute(self, item_label: str) -> dict:
        is_producible = item_label in PRODUCTION_CHAIN

        async with aiohttp.ClientSession() as session:
            prices = await market.fetch_prices(session)
            if not prices:
                raise NotFoundError("Fetch harga gagal")

            current_price = prices.get(item_label)
            if current_price is None:
                raise NotFoundError(f"Harga '{item_label}' tidak tersedia")

            orderbook = await market.fetch_orderbook(session, item_label)
            orderbook_failed = orderbook is None

            raw_data = await market.get_bonus_raw_data(session, with_cache=True)
            auto_bonus: dict[str, float] = {}
            median_bonus: dict[str, float] = {}
            if raw_data:
                countries, _ = raw_data
                countries_by_id = {c["_id"]: c for c in countries if c.get("_id")}
                party_ids = list({
                    c.get("rulingParty") for c in countries_by_id.values()
                    if c.get("rulingParty")
                })
                parties_by_id = await market._fetch_parties_batch(session, party_ids)
                auto_bonus = await market.fetch_max_bonuses(
                    session, raw_data=raw_data, parties_by_id=parties_by_id,
                )
                median_bonus = await market.fetch_median_bonuses(
                    session, raw_data=raw_data, parties_by_id=parties_by_id,
                )

        get_bonus = _make_get_bonus(auto_bonus)
        get_median_bonus = _make_get_median_bonus(median_bonus)

        cost = fp_compute_cost_engine(
            prices, item_label, is_producible, get_median_bonus, get_bonus,
        )
        if cost is None:
            raise NotFoundError(f"Cost engine '{item_label}' gagal (data tidak cukup)")

        pp_value = cost["pp_value"]
        cost_info = cost["cost_info"]
        bonus_best_pct = cost["bonus_best_pct"]
        production_cost = cost["production_cost"]
        break_even = cost["break_even"]

        ob = fp_parse_orderbook(orderbook)
        best_bid = ob["best_bid"]
        best_ask = ob["best_ask"]
        buy_vol = ob["buy_vol"]
        sell_vol = ob["sell_vol"]
        total_qty = ob["total_qty"]
        spread_pct = ob["spread_pct"]
        spread_label = ob["spread_label"]
        spread_key = ob["spread_key"]

        anchor = queries_fairprice.get_latest_anchor()
        anchor_age = _anchor_age_days(anchor)

        liq_data = None
        if is_producible:
            cutoff_7d = datetime.now(timezone.utc) - timedelta(days=LIQ_CUTOFF_DAYS)
            median_row = queries_fairprice.get_liquidity_median(
                item_label, cutoff_7d, lookback_days=LIQ_LOOKBACK_DAYS,
            )
            history_days = int(median_row["history_days"]) if median_row else 0
            median_notional = (
                float(median_row["median_notional"]) if median_row and median_row.get("median_notional") is not None else None
            )
            liq_data = _compute_liquidity_score(item_label, history_days, median_notional, anchor)

        liq_view = fp_compute_liquidity_view(liq_data, is_producible)
        if liq_view is None:
            raise NotFoundError(f"Liquidity '{item_label}' tidak cukup")

        weight_tech = liq_view["weight_tech"]
        weight_intr = liq_view["weight_intr"]
        margin_pct = liq_view["margin_pct"]
        liq_score = liq_view["liq_score"]
        liq_key = liq_view["liq_key"]
        liquidity_label = liq_view["liquidity_label"]

        intrinsic_value = production_cost if is_producible else 0.0

        history_rows = queries_fairprice.get_price_history(item_label, hours=TREND_WINDOW_HOURS)
        history = [(row["recorded_at"], float(row["price"])) for row in history_rows]

        now = datetime.now(timezone.utc)
        tv = fp_compute_technical_value(history, current_price, is_producible, now)
        if tv is None:
            raise NotFoundError(f"Technical value '{item_label}' tidak cukup")
        technical_value = tv["technical_value"]

        fr = fp_compute_fair_range(
            technical_value, intrinsic_value, weight_tech, weight_intr,
            margin_pct, is_producible, production_cost, best_bid,
        )
        fair_value = fr["fair_value"]
        fair_price = fr["fair_price"]
        fair_lower = fr["fair_lower"]
        fair_upper = fr["fair_upper"]
        good_buy = fr["good_buy"]
        good_sell = fr["good_sell"]

        val = fp_compute_valuation(
            current_price, fair_price, fair_lower, fair_upper, fair_value,
        )
        valuation_pct = val["valuation_pct"]
        valuation_key = val["valuation_key"]
        expected_edge = val["expected_edge"]

        trend_label, trend_key = _fetch_trend_30d(item_label)

        conf = fp_compute_confidence(
            spread_key, len(history), best_bid is not None, best_ask is not None,
            is_producible, cost_info, pp_value,
        )
        effective_conf = conf["effective_conf"]

        trend_opposes = (
            (valuation_key == "Undervalued" and trend_key == "Bearish") or
            (valuation_key == "Overvalued" and trend_key == "Bullish")
        )
        risk_label = fp_compute_risk(
            spread_key, is_producible, liq_score, effective_conf, trend_opposes,
        )

        from services.economy.constants import CONFIDENCE_GATE
        low_confidence = effective_conf < CONFIDENCE_GATE
        recommendation = fp_decide_recommendation(
            low_confidence, current_price, good_buy, good_sell,
        )

        reason_key = _fp_reason_key(recommendation, valuation_key, low_confidence)
        reasons = fp_compute_reasons(
            reason_key, valuation_key, valuation_pct, spread_key,
            is_producible, liq_key, liq_score, orderbook_failed,
            trend_opposes, trend_key,
        )

        data_confidence = fp_compute_data_confidence(liq_data, is_producible, anchor_age)

        pe = queries_fairprice.get_price_extremes(item_label)
        price_extremes = None
        if pe and pe.get("recorded_high") is not None and pe.get("recorded_low") is not None:
            price_extremes = {
                "recorded_high": float(pe["recorded_high"]),
                "recorded_high_date": str(pe.get("recorded_high_date") or ""),
                "recorded_low": float(pe["recorded_low"]),
                "recorded_low_date": str(pe.get("recorded_low_date") or ""),
                "tracked_since": str(pe.get("tracked_since") or ""),
            }

        return {
            "item": item_label,
            "current_price": current_price,
            "production_cost": production_cost,
            "break_even": break_even,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_pct": spread_pct,
            "spread_label": spread_label,
            "spread_key": spread_key,
            "liquidity_label": liquidity_label,
            "liquidity_score": liq_score,
            "weight_tech": weight_tech,
            "weight_intr": weight_intr,
            "total_qty": total_qty,
            "margin_pct": margin_pct,
            "fair_value": fair_value,
            "fair_price": fair_price,
            "fair_lower": fair_lower,
            "fair_upper": fair_upper,
            "good_buy": good_buy,
            "good_sell": good_sell,
            "valuation_key": valuation_key,
            "valuation_pct": valuation_pct,
            "expected_edge": expected_edge,
            "trend_label": trend_label,
            "trend_key": trend_key,
            "risk_label": risk_label,
            "recommendation": recommendation,
            "reason_key": reason_key,
            "reasons": reasons,
            "data_confidence": data_confidence,
            "price_extremes": price_extremes,
            "bonus_median_pct": cost_info["bonus_pct"] if is_producible else None,
            "bonus_median_source": cost_info["bonus_source"] if is_producible else "not_applicable",
            "bonus_best_pct": bonus_best_pct,
        }
