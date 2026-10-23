"""Logika Territory: validasi rentang WIB, resolve negara, panggil queries. Tanpa fastapi."""
from datetime import datetime, timedelta, timezone

from webapp.core.errors import NotFoundError, ValidationAppError

TAX_DATE_FORMAT = "%Y-%m-%d"
TAX_MAX_RANGE_DAYS = 90
WIB_OFFSET = timedelta(hours=7)
DEFAULT_RANGE_DAYS = 7
EVENTS_DEFAULT_LIMIT = 50
EVENTS_MAX_LIMIT = 200
LEADERBOARD_DEFAULT_LIMIT = 10
LEADERBOARD_MAX_LIMIT = 50


def _today_wib():
    return (datetime.now(timezone.utc) + WIB_OFFSET).date()


def wib_date_to_utc_bounds(from_str: str, to_str: str) -> tuple[datetime, datetime]:
    """('YYYY-MM-DD','YYYY-MM-DD') -> (since_utc, until_utc) — until exclusive."""
    from_date = datetime.strptime(from_str, TAX_DATE_FORMAT)
    to_date = datetime.strptime(to_str, TAX_DATE_FORMAT)
    since_dt = (from_date - WIB_OFFSET).replace(tzinfo=timezone.utc)
    until_dt = (to_date + timedelta(days=1) - WIB_OFFSET).replace(tzinfo=timezone.utc)
    return since_dt, until_dt


def parse_date_range(from_str: str, to_str: str) -> tuple[datetime, datetime, str, str]:
    """Validasi & normalisasi rentang tanggal (kalender WIB). Raise ValidationAppError."""
    today = _today_wib()
    if not from_str:
        from_str = (today - timedelta(days=DEFAULT_RANGE_DAYS - 1)).strftime(TAX_DATE_FORMAT)
    if not to_str:
        to_str = today.strftime(TAX_DATE_FORMAT)

    try:
        from_date = datetime.strptime(from_str, TAX_DATE_FORMAT)
        to_date = datetime.strptime(to_str, TAX_DATE_FORMAT)
    except ValueError:
        raise ValidationAppError("'from' dan 'to' harus format YYYY-MM-DD")

    if from_date > to_date:
        raise ValidationAppError("'from' harus <= 'to'")
    if to_date.date() > today:
        raise ValidationAppError("'to' tidak boleh di masa depan")
    if (to_date - from_date).days + 1 > TAX_MAX_RANGE_DAYS:
        raise ValidationAppError(f"rentang maksimal {TAX_MAX_RANGE_DAYS} hari")

    since_dt, until_dt = wib_date_to_utc_bounds(from_str, to_str)
    return since_dt, until_dt, from_str, to_str


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


class TerritoryService:
    def __init__(self, territory_queries) -> None:
        self._q = territory_queries

    def _resolve_country(self, raw_name: str) -> tuple[str, str]:
        """Port dari market._search_country_by_name: exact match dulu, lalu substring."""
        query = (raw_name or "").strip().lower()
        if not query:
            raise NotFoundError("nama negara kosong")
        countries = self._q.get_countries()
        for c in countries:
            if (c.get("name") or "").lower() == query:
                return c["_id"], c["name"]
        for c in countries:
            if query in (c.get("name") or "").lower():
                return c["_id"], c["name"]
        raise NotFoundError(f"negara tidak ditemukan: {raw_name}")

    def get_leaderboard(self, from_str: str, to_str: str, limit: int) -> dict:
        since_dt, until_dt, from_str, to_str = parse_date_range(from_str, to_str)
        limit = _clamp(limit or LEADERBOARD_DEFAULT_LIMIT, 1, LEADERBOARD_MAX_LIMIT)
        rows = self._q.get_top_tax_countries(since_dt, until_dt, limit)
        name_map = {c["_id"]: c.get("name", c["_id"]) for c in self._q.get_countries()}
        for row in rows:
            row["country_name"] = name_map.get(row["country_id"], row["country_id"])
        return {"from": from_str, "to": to_str, "leaderboard": rows}

    def get_country(self, raw_name: str, from_str: str, to_str: str) -> dict:
        country_id, country_name = self._resolve_country(raw_name)
        since_dt, until_dt, from_str, to_str = parse_date_range(from_str, to_str)
        summary = self._q.get_country_tax_summary(country_id, since_dt, until_dt)
        daily = self._q.get_country_tax_daily(country_id, since_dt, until_dt)
        daily = [
            {**d, "day": d["day"].date().isoformat() if d.get("day") else None}
            for d in daily
        ]
        return {
            "country_id": country_id,
            "country_name": country_name,
            "from": from_str,
            "to": to_str,
            "summary": summary,
            "daily": daily,
        }

    def get_events(self, raw_name: str, limit: int) -> dict:
        country_id, country_name = self._resolve_country(raw_name)
        limit = _clamp(limit or EVENTS_DEFAULT_LIMIT, 1, EVENTS_MAX_LIMIT)
        events = self._q.get_country_tax_events(country_id, limit)
        return {
            "country_id": country_id,
            "country_name": country_name,
            "events": events,
        }
