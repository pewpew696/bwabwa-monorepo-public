# fiscal_service.py
"""Logika Fiscal Monitor: leaderboard pajak global + tren + drilldown negara.

Baca dari territory_hourly_country_fiscal (rollup per-jam). Tanpa fastapi,
tanpa request ke API WarEra — murni baca DB lokal."""

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field

from webapp.core.errors import NotFoundError, ValidationAppError

# Window yang didukung (label -> jam).
WINDOWS = {
    "24h": 24,
    "7d": 24 * 7,
    "30d": 24 * 30,
}
DEFAULT_WINDOW = "24h"
LEADERBOARD_LIMIT = 20


class WindowInput(BaseModel):
    """Validasi query param window."""

    model_config = ConfigDict(extra="forbid")

    window: str = Field(default=DEFAULT_WINDOW)

    def hours(self) -> int:
        if self.window not in WINDOWS:
            raise ValidationAppError(f"window harus salah satu: {', '.join(WINDOWS)}")
        return WINDOWS[self.window]


def _window_bounds(window_hours: int) -> tuple[datetime, datetime]:
    """(since, until) hour-aligned UTC, until exclusive."""
    now = datetime.now(timezone.utc)
    until = now.replace(minute=0, second=0, microsecond=0)
    since = until - timedelta(hours=window_hours)
    return since, until


def _fnum(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


class FiscalService:
    def __init__(self, fiscal_queries) -> None:
        self._q = fiscal_queries

    def get_overview(self, window: str) -> dict:
        hours = WindowInput(window=window).hours()
        since, until = _window_bounds(hours)
        names = self._q.get_country_names()
        summary = self._q.get_summary(since, until)
        rows = self._q.get_leaderboard(since, until, LEADERBOARD_LIMIT)
        trend = self._q.get_global_trend(since, until)
        return {
            "window": window,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "summary": {
                "tax_income": _fnum(summary.get("tax_income")),
                "wages_paid": _fnum(summary.get("wages_paid")),
                "transactions": int(summary.get("transactions") or 0),
                "countries": int(summary.get("countries") or 0),
            },
            "leaderboard": [
                {
                    "country_id": r["country_id"],
                    "country_name": names.get(r["country_id"], r["country_id"][:8]),
                    "tax_income": _fnum(r["tax_income"]),
                    "wages_paid": _fnum(r["wages_paid"]),
                    "transactions": int(r["transactions"] or 0),
                    "avg_tax_rate": _fnum(r["avg_tax_rate"]),
                    "foreign_tax": _fnum(r["foreign_tax"]),
                    "domestic_tax": _fnum(r["domestic_tax"]),
                }
                for r in rows
            ],
            "trend": [
                {
                    "hour": r["hour"].isoformat() if hasattr(r["hour"], "isoformat") else str(r["hour"]),
                    "ts": int(r["hour"].timestamp()) if hasattr(r["hour"], "timestamp") else 0,
                    "tax_income": _fnum(r["tax_income"]),
                    "wages_paid": _fnum(r["wages_paid"]),
                }
                for r in trend
            ],
            "windows": list(WINDOWS),
        }

    def get_country_detail(self, country_id: str, window: str) -> dict:
        if not country_id or len(country_id) > 64:
            raise ValidationAppError("country_id tidak valid")
        hours = WindowInput(window=window).hours()
        since, until = _window_bounds(hours)
        names = self._q.get_country_names()
        name = names.get(country_id)
        if not name:
            raise NotFoundError(f"negara tidak ditemukan: {country_id}")
        total = self._q.get_country_total(country_id, since, until)
        trend = self._q.get_country_trend(country_id, since, until)
        # Breakdown: owner country, item, region (khusus drilldown).
        raw_owner = self._q.get_breakdown_by_owner(country_id, since, until)
        raw_item = self._q.get_breakdown_by_item(country_id, since, until)
        raw_region = self._q.get_breakdown_by_region(country_id, since, until)
        tax_income = _fnum(total.get("tax_income"))
        foreign = _fnum(total.get("foreign_tax"))
        return {
            "window": window,
            "country_id": country_id,
            "country_name": name,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "total": {
                "tax_income": tax_income,
                "wages_paid": _fnum(total.get("wages_paid")),
                "transactions": int(total.get("transactions") or 0),
                "avg_tax_rate": _fnum(total.get("avg_tax_rate")),
                "foreign_tax": foreign,
                "domestic_tax": _fnum(total.get("domestic_tax")),
                "tax_to_worker_country": _fnum(total.get("tax_to_worker_country")),
                # Upgrade vs xorgress: split foreign/domestic.
                "foreign_share_pct": round(foreign / tax_income * 100, 1) if tax_income else 0.0,
            },
            "trend": [
                {
                    "hour": r["hour"].isoformat() if hasattr(r["hour"], "isoformat") else str(r["hour"]),
                    "ts": int(r["hour"].timestamp()) if hasattr(r["hour"], "timestamp") else 0,
                    "tax_income": _fnum(r["tax_income"]),
                    "wages_paid": _fnum(r["wages_paid"]),
                    "foreign_tax": _fnum(r["foreign_tax"]),
                    "domestic_tax": _fnum(r["domestic_tax"]),
                }
                for r in trend
            ],
            "by_owner": [
                {
                    "country_id": r["dim"] or "",
                    "country_name": names.get(r["dim"], "Unknown") if r["dim"] else "Unknown",
                    "tax_income": _fnum(r["tax_income"]),
                    "wages_paid": _fnum(r["wages_paid"]),
                    "transactions": int(r["transactions"] or 0),
                }
                for r in raw_owner
            ],
            "by_item": [
                {
                    "item_code": r["dim"] or "Unknown",
                    "tax_income": _fnum(r["tax_income"]),
                    "wages_paid": _fnum(r["wages_paid"]),
                    "transactions": int(r["transactions"] or 0),
                }
                for r in raw_item
            ],
            "by_region": [
                {
                    "region_id": r["dim"] or "Unknown",
                    "tax_income": _fnum(r["tax_income"]),
                    "wages_paid": _fnum(r["wages_paid"]),
                    "transactions": int(r["transactions"] or 0),
                }
                for r in raw_region
            ],
            "windows": list(WINDOWS),
        }
