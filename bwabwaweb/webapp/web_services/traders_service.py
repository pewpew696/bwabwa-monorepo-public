"""Logika Traders: leaderboard trader dari cache bot. Tanpa fastapi."""
from dataclasses import dataclass

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


@dataclass(frozen=True)
class TraderRow:
    user_id: str
    username: str
    win_rate: float | None
    closed_trades: int
    wins: int
    losses: int
    net_profit: float
    best_item_code: str | None
    best_item_profit: float | None


@dataclass(frozen=True)
class TradersReport:
    total: int
    limit: int
    rows: list[TraderRow]


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_float_required(value) -> float:
    v = _safe_float(value)
    return v if v is not None else 0.0


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


class TradersService:
    def __init__(self, traders_queries) -> None:
        self._q = traders_queries

    def get_leaderboard(self, limit: int = DEFAULT_LIMIT) -> TradersReport:
        limit = _clamp(limit or DEFAULT_LIMIT, 1, MAX_LIMIT)
        rows = self._q.get_trade_leaderboard(limit)
        total = self._q.get_traders_total()
        return TradersReport(
            total=total,
            limit=limit,
            rows=[
                TraderRow(
                    user_id=r["user_id"],
                    username=r.get("username") or r["user_id"][:8] + "…",
                    win_rate=_safe_float(r.get("win_rate")),
                    closed_trades=_safe_int(r.get("closed_trades")),
                    wins=_safe_int(r.get("wins")),
                    losses=_safe_int(r.get("losses")),
                    net_profit=_safe_float_required(r.get("net_profit")),
                    best_item_code=r.get("best_item_code"),
                    best_item_profit=_safe_float(r.get("best_item_profit")),
                )
                for r in rows
            ],
        )
