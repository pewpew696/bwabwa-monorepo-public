"""Query bonus item: item_bonus_deposits + country_tax_snapshot (read-only)."""
from webapp.core.database import fetch_dicts, web_session

BONUS_WITH_TAX_SQL = """
SELECT d.item_name, d.country_name, d.pct, d.rank_no, d.ends_at, d.fetched_at,
       t.tax_pct
FROM item_bonus_deposits d
LEFT JOIN country_tax_snapshot t ON t.country_name = d.country_name
WHERE d.ends_at IS NULL OR d.ends_at > now()
ORDER BY d.item_name ASC, d.rank_no ASC NULLS LAST, d.pct DESC
"""


def get_active_bonus_rows() -> list[dict]:
    with web_session() as cursor:
        cursor.execute(BONUS_WITH_TAX_SQL)
        return fetch_dicts(cursor)
