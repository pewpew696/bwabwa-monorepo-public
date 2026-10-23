# queries_companies.py
"""Query Company Explorer: agregasi company_index dari DB (bot yang fetch).
Tanpa fetch API WarEra di sini — hanya baca cache api_cache."""

from webapp.core.database import fetch_dicts, web_session

ITEM_SUMMARY_SQL = """
SELECT
  item_code,
  COUNT(*) AS companies,
  COALESCE(SUM(worker_count), 0) AS total_workers,
  COUNT(*) FILTER (WHERE ae_level > 0) AS with_ae,
  MAX(updated_at) AS last_updated
FROM company_index
GROUP BY item_code
ORDER BY companies DESC
"""

ITEM_AE_BREAKDOWN_SQL = """
SELECT
  ae_level,
  COUNT(*) AS companies,
  COALESCE(SUM(worker_count), 0) AS total_workers
FROM company_index
WHERE item_code = %s
GROUP BY ae_level
ORDER BY ae_level ASC
"""

ITEM_COUNTRY_SQL = """
SELECT
  region_id,
  COUNT(*) AS companies,
  COALESCE(SUM(worker_count), 0) AS total_workers
FROM company_index
WHERE item_code = %s
  AND region_id IS NOT NULL
GROUP BY region_id
ORDER BY companies DESC
"""

# Baca api_cache (countries & regions_obj). regions_obj = dict region_id -> region.
API_CACHE_SQL = "SELECT data FROM api_cache WHERE cache_key = %s"


def get_item_summary() -> list[dict]:
    with web_session() as cur:
        cur.execute(ITEM_SUMMARY_SQL)
        return fetch_dicts(cur)


def get_item_ae_breakdown(item_code: str) -> list[dict]:
    with web_session() as cur:
        cur.execute(ITEM_AE_BREAKDOWN_SQL, (item_code,))
        return fetch_dicts(cur)


def get_item_country_rows(item_code: str) -> list[dict]:
    """Agregasi per region_id dari SQL — mapping ke negara dilakukan di service
    layer via get_region_country_map() (tanpa JOIN ke JSON di SQL)."""
    with web_session() as cur:
        cur.execute(ITEM_COUNTRY_SQL, (item_code,))
        return fetch_dicts(cur)


def get_region_country_map() -> dict:
    """{region_id: region} dari api_cache key 'regions_obj' (region['country']=country_id)."""
    with web_session() as cur:
        cur.execute(API_CACHE_SQL, ("regions_obj",))
        rows = fetch_dicts(cur)
    if not rows:
        return {}
    data = rows[0].get("data") or {}
    return data if isinstance(data, dict) else {}
