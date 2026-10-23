"""Indikator teknikal (pandas). Fungsi murni, tanpa DB, tanpa fastapi."""
from dataclasses import dataclass

import pandas as pd

MIN_ROWS = 7
MA_FAST = 7
MA_SLOW = 30
EMA_PERIOD = 13
RSI_PERIOD = 14
BOLL_PERIOD = 20
BOLL_STD = 2
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


@dataclass(frozen=True)
class IndicatorBundle:
    available: bool
    ma_fast: list[float | None]
    ma_slow: list[float | None]
    ema: list[float | None]
    rsi: list[float | None]
    boll_upper: list[float | None]
    boll_lower: list[float | None]
    macd: list[float | None]
    macd_signal: list[float | None]


def _to_series(prices: list[float]) -> pd.Series:
    return pd.Series(prices, dtype="float64")


def _none_list(series: pd.Series) -> list[float | None]:
    return [None if pd.isna(v) else round(float(v), 6) for v in series]


def compute_indicators(prices: list[float]) -> IndicatorBundle:
    if len(prices) < MIN_ROWS:
        empty: list[float | None] = []
        return IndicatorBundle(False, empty, empty, empty, empty, empty, empty, empty, empty)

    s = _to_series(prices)

    ma_fast = s.rolling(MA_FAST, min_periods=MA_FAST).mean()
    ma_slow = s.rolling(MA_SLOW, min_periods=MA_SLOW).mean() if len(s) >= MA_SLOW else pd.Series([None] * len(s))
    ema = s.ewm(span=EMA_PERIOD, adjust=False).mean()

    delta = s.diff()
    gain = delta.clip(lower=0).rolling(RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    loss = (-delta.clip(upper=0)).rolling(RSI_PERIOD, min_periods=RSI_PERIOD).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))

    if len(s) >= BOLL_PERIOD:
        boll_mid = s.rolling(BOLL_PERIOD, min_periods=BOLL_PERIOD).mean()
        boll_std = s.rolling(BOLL_PERIOD, min_periods=BOLL_PERIOD).std(ddof=0)
        boll_upper = boll_mid + BOLL_STD * boll_std
        boll_lower = boll_mid - BOLL_STD * boll_std
    else:
        boll_upper = pd.Series([None] * len(s))
        boll_lower = pd.Series([None] * len(s))

    ema_fast = s.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = s.ewm(span=MACD_SLOW, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()

    return IndicatorBundle(
        available=True,
        ma_fast=_none_list(ma_fast),
        ma_slow=_none_list(ma_slow),
        ema=_none_list(ema),
        rsi=_none_list(rsi),
        boll_upper=_none_list(boll_upper),
        boll_lower=_none_list(boll_lower),
        macd=_none_list(macd),
        macd_signal=_none_list(macd_signal),
    )
