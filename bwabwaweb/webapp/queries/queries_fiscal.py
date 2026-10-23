# queries_fiscal.py
"""Query Fiscal Monitor: baca dari territory_hourly_country_fiscal (rollup),
bukan dari events mentah. Tanpa fastapi."""

from webapp.core.database import fetch_dicts, web_session
from services.territory.fiscal_rollup import ensure_fiscal_table
from services.territory.fiscal_breakdown_rollup import ensure_breakdown_table

_table_ensured = False


def _ensure_table():
    """Pastikan tabel rollup ada (idempotent, aman tiap request)."""
    global _table_ensured
    if not _table_ensured:
        ensure_fiscal_table()
        _table_ensured = True


def _ensure_breakdown():
    """Pastikan tabel breakdown ada (idempotent)."""
    ensure_breakdown_table()


LEADERBOARD_SQL = """
SELECT
    r.country_id,
    COALESCE(SUM(r.tax_income), 0) AS tax_income,
    COALESCE(SUM(r.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(r.transactions), 0) AS transactions,
    AVG(r.avg_tax_rate) AS avg_tax_rate,
    COALESCE(SUM(r.foreign_tax), 0) AS foreign_tax,
    COALESCE(SUM(r.domestic_tax), 0) AS domestic_tax
FROM territory_hourly_country_fiscal r
WHERE r.hour >= %s AND r.hour < %s
GROUP BY r.country_id
ORDER BY tax_income DESC
LIMIT %s
"""

TREND_SQL = """
SELECT
    r.hour,
    COALESCE(SUM(r.tax_income), 0) AS tax_income,
    COALESCE(SUM(r.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(r.transactions), 0) AS transactions
FROM territory_hourly_country_fiscal r
WHERE r.hour >= %s AND r.hour < %s
GROUP BY r.hour
ORDER BY r.hour ASC
"""

COUNTRY_TREND_SQL = """
SELECT
    r.hour,
    COALESCE(SUM(r.tax_income), 0) AS tax_income,
    COALESCE(SUM(r.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(r.transactions), 0) AS transactions,
    AVG(r.avg_tax_rate) AS avg_tax_rate,
    COALESCE(SUM(r.foreign_tax), 0) AS foreign_tax,
    COALESCE(SUM(r.domestic_tax), 0) AS domestic_tax,
    COALESCE(SUM(r.tax_to_worker_country), 0) AS tax_to_worker_country
FROM territory_hourly_country_fiscal r
WHERE r.country_id = %s
  AND r.hour >= %s AND r.hour < %s
GROUP BY r.hour
ORDER BY r.hour ASC
"""

COUNTRY_TOTAL_SQL = """
SELECT
    COALESCE(SUM(r.tax_income), 0) AS tax_income,
    COALESCE(SUM(r.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(r.transactions), 0) AS transactions,
    AVG(r.avg_tax_rate) AS avg_tax_rate,
    COALESCE(SUM(r.foreign_tax), 0) AS foreign_tax,
    COALESCE(SUM(r.domestic_tax), 0) AS domestic_tax,
    COALESCE(SUM(r.tax_to_worker_country), 0) AS tax_to_worker_country
FROM territory_hourly_country_fiscal r
WHERE r.country_id = %s
  AND r.hour >= %s AND r.hour < %s
"""

SUMMARY_SQL = """
SELECT
    COALESCE(SUM(r.tax_income), 0) AS tax_income,
    COALESCE(SUM(r.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(r.transactions), 0) AS transactions,
    COUNT(DISTINCT r.country_id) AS countries
FROM territory_hourly_country_fiscal r
WHERE r.hour >= %s AND r.hour < %s
"""

# Nama negara dari api_cache (sama seperti queries_territory).
COUNTRIES_SQL = "SELECT data FROM api_cache WHERE cache_key = %s"


def get_leaderboard(since, until, limit: int) -> list[dict]:
    _ensure_table()
    with web_session() as cur:
        cur.execute(LEADERBOARD_SQL, (since, until, limit))
        return fetch_dicts(cur)


def get_global_trend(since, until) -> list[dict]:
    _ensure_table()
    with web_session() as cur:
        cur.execute(TREND_SQL, (since, until))
        return fetch_dicts(cur)


def get_country_trend(country_id: str, since, until) -> list[dict]:
    _ensure_table()
    with web_session() as cur:
        cur.execute(COUNTRY_TREND_SQL, (country_id, since, until))
        return fetch_dicts(cur)


def get_country_total(country_id: str, since, until) -> dict:
    _ensure_table()
    with web_session() as cur:
        cur.execute(COUNTRY_TOTAL_SQL, (country_id, since, until))
        rows = fetch_dicts(cur)
    return rows[0] if rows else {}


def get_summary(since, until) -> dict:
    _ensure_table()
    with web_session() as cur:
        cur.execute(SUMMARY_SQL, (since, until))
        rows = fetch_dicts(cur)
    return rows[0] if rows else {}


def get_country_names() -> dict[str, str]:
    _ensure_table()
    """{country_id: name} dari api_cache."""
    with web_session() as cur:
        cur.execute(COUNTRIES_SQL, ("countries",))
        rows = fetch_dicts(cur)
    if not rows:
        return {}
    data = rows[0].get("data") or []
    return {c.get("_id"): c.get("name") for c in data if c.get("_id")}


# --- Breakdown drilldown country (dari territory_hourly_country_fiscal_breakdown) ---

BREAKDOWN_OWNER_SQL = """
SELECT
    b.owner_country_id AS dim,
    COALESCE(SUM(b.tax_income), 0) AS tax_income,
    COALESCE(SUM(b.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(b.transactions), 0) AS transactions
FROM territory_hourly_country_fiscal_breakdown b
WHERE b.country_id = %s
  AND b.hour >= %s AND b.hour < %s
GROUP BY b.owner_country_id
ORDER BY tax_income DESC
LIMIT 20
"""

BREAKDOWN_ITEM_SQL = """
SELECT
    b.item_code AS dim,
    COALESCE(SUM(b.tax_income), 0) AS tax_income,
    COALESCE(SUM(b.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(b.transactions), 0) AS transactions
FROM territory_hourly_country_fiscal_breakdown b
WHERE b.country_id = %s
  AND b.hour >= %s AND b.hour < %s
GROUP BY b.item_code
ORDER BY tax_income DESC
LIMIT 20
"""

BREAKDOWN_REGION_SQL = """
SELECT
    b.region_id AS dim,
    COALESCE(SUM(b.tax_income), 0) AS tax_income,
    COALESCE(SUM(b.wages_paid), 0) AS wages_paid,
    COALESCE(SUM(b.transactions), 0) AS transactions
FROM territory_hourly_country_fiscal_breakdown b
WHERE b.country_id = %s
  AND b.hour >= %s AND b.hour < %s
GROUP BY b.region_id
ORDER BY tax_income DESC
LIMIT 20
"""


def get_breakdown_by_owner(country_id: str, since, until) -> list[dict]:
    _ensure_breakdown()
    with web_session() as cur:
        cur.execute(BREAKDOWN_OWNER_SQL, (country_id, since, until))
        return fetch_dicts(cur)


def get_breakdown_by_item(country_id: str, since, until) -> list[dict]:
    _ensure_breakdown()
    with web_session() as cur:
        cur.execute(BREAKDOWN_ITEM_SQL, (country_id, since, until))
        return fetch_dicts(cur)


def get_breakdown_by_region(country_id: str, since, until) -> list[dict]:
    _ensure_breakdown()
    with web_session() as cur:
        cur.execute(BREAKDOWN_REGION_SQL, (country_id, since, until))
        return fetch_dicts(cur)
