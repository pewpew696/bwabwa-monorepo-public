"""Logika Bonus: kelompokkan bonus item + pajak per negara. Tanpa fastapi."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from services.economy.constants import ITEM_NOT_PRODUCIBLE

STALE_AFTER_SECONDS = 2 * 60 * 60  # bot refresh bonus tiap 60 menit; 2 jam = basi


@dataclass(frozen=True)
class BonusItem:
    item_name: str
    rows: list[dict]
    fetched_at: datetime | None
    is_stale: bool


class BonusService:
    def __init__(self, bonus_queries) -> None:
        self._bonus = bonus_queries

    def list_items(self) -> list[BonusItem]:
        rows = self._bonus.get_active_bonus_rows()
        now = datetime.now(timezone.utc)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            if row["item_name"] in ITEM_NOT_PRODUCIBLE:
                continue
            ends_at = row["ends_at"]
            if ends_at is not None and ends_at <= now:
                continue
            grouped[row["item_name"]].append(row)

        result: list[BonusItem] = []
        for name in sorted(grouped):
            item_rows = grouped[name]
            fetched = max((r["fetched_at"] for r in item_rows), default=None)
            is_stale = (
                fetched is None
                or (now - fetched).total_seconds() > STALE_AFTER_SECONDS
            )
            result.append(
                BonusItem(
                    item_name=name,
                    rows=item_rows,
                    fetched_at=fetched,
                    is_stale=is_stale,
                )
            )
        return result
