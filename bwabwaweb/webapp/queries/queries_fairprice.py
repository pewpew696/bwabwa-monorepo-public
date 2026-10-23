# webapp/queries/queries_fairprice.py — query DB untuk halaman fairprice (read-only).

from datetime import datetime, timedelta, timezone

from webapp.core.database import fetch_dicts, web_session

PRICE_HISTORY_SQL = """
    SELECT price, recorded_at
    FROM price_history
    WHERE item_name = %s
      AND recorded_at >= %s
    ORDER BY recorded_at ASC
"""

LATEST_ANCHOR_SQL = """
    SELECT * FROM liquidity_anchors
    ORDER BY calibrated_at DESC
    LIMIT 1
"""

LIQUIDITY_MEDIAN_SQL = """
    SELECT item_name, median_notional, history_days
    FROM liquidity_basket_medians(%s, %s)
    WHERE item_name = %s
"""

PRICE_EXTREMES_SQL = """
    SELECT item_name, recorded_high, recorded_high_date,
           recorded_low, recorded_low_date, tracked_since
    FROM price_extremes_all()
    WHERE item_name = %s
"""


def get_price_history(item_name: str, hours: int = 720) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with web_session() as cursor:
        cursor.execute(PRICE_HISTORY_SQL, (item_name, cutoff))
        return fetch_dicts(cursor)


def get_latest_anchor() -> dict | None:
    with web_session() as cursor:
        cursor.execute(LATEST_ANCHOR_SQL)
        rows = fetch_dicts(cursor)
    return rows[0] if rows else None


def get_liquidity_median(item_name: str, cutoff: datetime, lookback_days: int = 30) -> dict | None:
    with web_session() as cursor:
        cursor.execute(LIQUIDITY_MEDIAN_SQL, (cutoff, lookback_days, item_name))
        rows = fetch_dicts(cursor)
    return rows[0] if rows else None


def get_price_extremes(item_name: str) -> dict | None:
    with web_session() as cursor:
        cursor.execute(PRICE_EXTREMES_SQL, (item_name,))
        rows = fetch_dicts(cursor)
    return rows[0] if rows else None
