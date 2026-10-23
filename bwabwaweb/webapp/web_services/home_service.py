"""Logika Home: ringkasan market dari snapshot harga di DB. Tanpa fastapi."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MOVER_WINDOWS = ((24, "24 jam"), (168, "7 hari"))
MOVER_LIMIT = 5
ACTIVE_LIMIT = 8
SPREAD_LIMIT = 5
STALE_AFTER = timedelta(minutes=30)
SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class MoverBoard:
    label: str
    gainers: list[dict]
    losers: list[dict]


@dataclass(frozen=True)
class HomeData:
    as_of: datetime | None
    age_minutes: int | None
    is_stale: bool
    boards: list[MoverBoard]
    active_items: list[dict]
    wide_spreads: list[dict]

    @property
    def is_empty(self) -> bool:
        return self.as_of is None


def _compute_movers(rows: list[dict]) -> list[dict]:
    """Port logika lama: lewati item <2 titik atau harga awal 0; ubah = (baru-lama)/lama*100."""
    movers = []
    for row in rows:
        old_price, new_price = row["old_price"], row["new_price"]
        if row["first_at"] == row["last_at"] or not old_price or new_price is None:
            continue
        movers.append(
            {
                "item_name": row["item_name"],
                "price": new_price,
                "change_pct": (new_price - old_price) / old_price * 100,
            }
        )
    return movers


def _build_board(label: str, rows: list[dict]) -> MoverBoard:
    movers = _compute_movers(rows)
    gainers = sorted(
        (mover for mover in movers if mover["change_pct"] > 0),
        key=lambda mover: (-mover["change_pct"], mover["item_name"]),
    )
    losers = sorted(
        (mover for mover in movers if mover["change_pct"] < 0),
        key=lambda mover: (mover["change_pct"], mover["item_name"]),
    )
    return MoverBoard(label=label, gainers=gainers[:MOVER_LIMIT], losers=losers[:MOVER_LIMIT])


def _rank_active(latest: list[dict]) -> list[dict]:
    """Nilai transaksi NULL atau 0 (volume kosong) tidak ikut ranking."""
    ranked = [row for row in latest if row["traded_value"]]
    ranked.sort(key=lambda row: (-row["traded_value"], row["item_name"]))
    return ranked[:ACTIVE_LIMIT]


def _rank_spreads(latest: list[dict]) -> list[dict]:
    ranked = [row for row in latest if row["spread_pct"] is not None]
    ranked.sort(key=lambda row: (-row["spread_pct"], row["item_name"]))
    return ranked[:SPREAD_LIMIT]


class HomeService:
    def __init__(self, market_store) -> None:
        self._market = market_store

    def get_home(self, now: datetime | None = None) -> HomeData:
        now = now or datetime.now(timezone.utc)
        data = self._market.get_home_market_data(tuple(hours for hours, _ in MOVER_WINDOWS))
        latest = data["latest"]
        boards = [_build_board(label, data["movers"][hours]) for hours, label in MOVER_WINDOWS]
        as_of = max((row["recorded_at"] for row in latest), default=None)
        age = None if as_of is None else now - as_of
        age_minutes = None if age is None else int(age.total_seconds() // SECONDS_PER_MINUTE)
        return HomeData(
            as_of=as_of,
            age_minutes=age_minutes,
            is_stale=age is None or age > STALE_AFTER,
            boards=boards,
            active_items=_rank_active(latest),
            wide_spreads=_rank_spreads(latest),
        )
