"""Query Traders: leaderboard dari trade_profile + username_cache (read-only)."""
from webapp.core.database import fetch_dicts, web_session

DEFAULT_LIMIT = 25
MAX_LIMIT = 100

LEADERBOARD_SQL = """
SELECT p.user_id,
       u.username,
       p.win_rate,
       p.closed_trades,
       p.wins,
       p.losses,
       p.net_profit,
       p.best_item_code,
       p.best_item_profit,
       p.last_trade_at
FROM trade_profile p
LEFT JOIN username_cache u ON u.user_id = p.user_id
WHERE p.closed_trades > 0
ORDER BY p.net_profit DESC
LIMIT %s
"""

COUNT_SQL = "SELECT count(*) AS total FROM trade_profile WHERE closed_trades > 0"


def get_trade_leaderboard(limit: int = DEFAULT_LIMIT) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(LEADERBOARD_SQL, (limit,))
        return fetch_dicts(cursor)


def get_traders_total() -> int:
    with web_session() as cursor:
        cursor.execute(COUNT_SQL)
        rows = fetch_dicts(cursor)
    return int(rows[0]["total"]) if rows else 0
