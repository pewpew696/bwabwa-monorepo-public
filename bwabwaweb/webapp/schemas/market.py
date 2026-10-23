"""Schema response Market: OHLC + indikator chart."""
from pydantic import BaseModel


class OHLCBar(BaseModel):
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float


class IndicatorPoint(BaseModel):
    t: int
    v: float | None


class BollPoint(BaseModel):
    t: int
    upper: float | None
    lower: float | None


class MacdPoint(BaseModel):
    t: int
    macd: float | None
    signal: float | None
    hist: float | None


class IndicatorsBundle(BaseModel):
    available: bool
    ma7: list[IndicatorPoint]
    ma30: list[IndicatorPoint]
    ema13: list[IndicatorPoint]
    boll: list[BollPoint]
    rsi14: list[IndicatorPoint]
    macd: list[MacdPoint]


class OhlcResponse(BaseModel):
    item_name: str
    range_hours: int
    bin_hours: int
    bars: list[OHLCBar]
    indicators: IndicatorsBundle


class OhlcBasicResponse(BaseModel):
    item_name: str
    range_hours: int
    bin_hours: int
    bars: list[OHLCBar]
