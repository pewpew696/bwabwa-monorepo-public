"""Query Territory: port setia dari services/territory/tax_store.py via local_session().

Semua query pajak WAJIB menyertakan filter income_tax_rate IS NOT NULL
(mengikuti tax_store.py — jangan dihilangkan).
"""
from webapp.core.database import fetch_dicts, web_session

COUNTRIES_CACHE_KEY = "countries"

TAX_SUMMARY_SQL = """
SELECT
  COUNT(*) AS tx_count,
  COALESCE(SUM(gross_tax), 0) AS gross_tax_total,
  COALESCE(SUM(tax_to_operating_country), 0) AS tax_collected,
  COALESCE(SUM(money), 0) AS wage_volume,
  COUNT(*) FILTER (WHERE is_foreign_worker IS TRUE) AS foreign_tx_count,
  COALESCE(SUM(gross_tax) FILTER (WHERE is_foreign_worker IS TRUE), 0) AS foreign_gross_tax,
  COUNT(*) FILTER (WHERE is_foreign_worker IS FALSE) AS domestic_tx_count,
  COALESCE(SUM(gross_tax) FILTER (WHERE is_foreign_worker IS FALSE), 0) AS domestic_gross_tax,
  COUNT(DISTINCT company_id) AS company_count
FROM territory_wage_events
WHERE operating_country_id = %s
  AND created_at >= %s
  AND created_at < %s
  AND income_tax_rate IS NOT NULL
"""

TAX_SENT_SQL = """
SELECT
  COUNT(*) AS tx_count,
  COALESCE(SUM(tax_to_worker_country), 0) AS tax_sent
FROM territory_wage_events
WHERE worker_citizenship_country_id = %s
  AND operating_country_id IS DISTINCT FROM %s
  AND created_at >= %s
  AND created_at < %s
  AND income_tax_rate IS NOT NULL
"""

TAX_DAILY_SQL = """
SELECT
  date_trunc('day', created_at) AS day,
  COUNT(*) AS tx_count,
  COALESCE(SUM(gross_tax), 0) AS gross_tax_total,
  COALESCE(SUM(tax_to_operating_country), 0) AS tax_collected
FROM territory_wage_events
WHERE operating_country_id = %s
  AND created_at >= %s
  AND created_at < %s
  AND income_tax_rate IS NOT NULL
GROUP BY 1
ORDER BY 1 ASC
"""

TAX_EVENTS_SQL = """
SELECT tx_id, created_at, seller_id, buyer_id, company_id,
       money, income_tax_rate, gross_tax, tax_to_operating_country,
       tax_to_worker_country, is_foreign_worker, worker_citizenship_country_id
FROM territory_wage_events
WHERE operating_country_id = %s
  AND income_tax_rate IS NOT NULL
ORDER BY created_at DESC
LIMIT %s
"""

TOP_COUNTRIES_SQL = """
SELECT
  operating_country_id AS country_id,
  COUNT(*) AS tx_count,
  COALESCE(SUM(gross_tax), 0) AS gross_tax_total,
  COALESCE(SUM(tax_to_operating_country), 0) AS tax_collected
FROM territory_wage_events
WHERE operating_country_id IS NOT NULL
  AND created_at >= %s
  AND created_at < %s
  AND income_tax_rate IS NOT NULL
GROUP BY 1
ORDER BY 4 DESC
LIMIT %s
"""

COUNTRIES_SQL = "SELECT data FROM api_cache WHERE cache_key = %s"

SUMMARY_FLOAT_KEYS = (
    "gross_tax_total", "tax_collected", "wage_volume",
    "foreign_gross_tax", "domestic_gross_tax",
)
EVENT_FLOAT_KEYS = (
    "money", "income_tax_rate", "gross_tax",
    "tax_to_operating_country", "tax_to_worker_country",
)
TOP_FLOAT_KEYS = ("gross_tax_total", "tax_collected")


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _floatify(row: dict, keys: tuple[str, ...]) -> dict:
    for k in keys:
        if k in row:
            row[k] = _to_float(row[k])
    return row


def get_country_tax_summary(country_id: str, since_dt, until_dt) -> dict:
    with web_session() as cursor:
        cursor.execute(TAX_SUMMARY_SQL, (country_id, since_dt, until_dt))
        summary_rows = fetch_dicts(cursor)
        cursor.execute(TAX_SENT_SQL, (country_id, country_id, since_dt, until_dt))
        sent_rows = fetch_dicts(cursor)
    if not summary_rows or not sent_rows:
        return {}
    collected = _floatify(summary_rows[0], SUMMARY_FLOAT_KEYS)
    sent = _floatify(sent_rows[0], ("tax_sent",))
    return {"collected": collected, "sent_to_citizens_abroad": sent}


def get_country_tax_daily(country_id: str, since_dt, until_dt) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(TAX_DAILY_SQL, (country_id, since_dt, until_dt))
        rows = fetch_dicts(cursor)
    for row in rows:
        _floatify(row, ("gross_tax_total", "tax_collected"))
    return rows


def get_country_tax_events(country_id: str, limit: int) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(TAX_EVENTS_SQL, (country_id, limit))
        rows = fetch_dicts(cursor)
    for row in rows:
        _floatify(row, EVENT_FLOAT_KEYS)
    return rows


def get_top_tax_countries(since_dt, until_dt, limit: int) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(TOP_COUNTRIES_SQL, (since_dt, until_dt, limit))
        rows = fetch_dicts(cursor)
    for row in rows:
        _floatify(row, TOP_FLOAT_KEYS)
    return rows


def get_countries() -> list[dict]:
    """Baca api_cache 'countries' (read-only)."""
    with web_session() as cursor:
        cursor.execute(COUNTRIES_SQL, (COUNTRIES_CACHE_KEY,))
        rows = fetch_dicts(cursor)
    if not rows:
        return []
    data = rows[0]["data"]
    return data if isinstance(data, list) else []
