"""Query market: Home (movers + item teraktif + spread) dan Market (chart + volume)."""
from webapp.core.database import fetch_dicts, web_session

# Daftar item tanpa DISTINCT ON di 300 ribu baris: lompat indeks (item_name, recorded_at DESC).
ITEMS_CTE = """
WITH RECURSIVE items AS (
  (SELECT item_name FROM price_history ORDER BY item_name LIMIT 1)
  UNION ALL
  SELECT (SELECT p.item_name FROM price_history p
          WHERE p.item_name > i.item_name ORDER BY p.item_name LIMIT 1)
  FROM items i WHERE i.item_name IS NOT NULL
)
"""

LATEST_PER_ITEM_SQL = ITEMS_CTE + """
SELECT i.item_name, l.price, l.bid, l.ask, l.volume, l.recorded_at,
       CASE WHEN l.bid IS NOT NULL AND l.ask IS NOT NULL
                 AND l.bid <= l.ask AND (l.ask + l.bid) > 0
            THEN (l.ask - l.bid) / ((l.ask + l.bid) / 2) * 100
       END AS spread_pct,
       l.volume * l.price AS traded_value
FROM items i
CROSS JOIN LATERAL (
  SELECT price, bid, ask, volume, recorded_at
  FROM price_history h
  WHERE h.item_name = i.item_name
  ORDER BY h.recorded_at DESC LIMIT 1
) l
WHERE i.item_name IS NOT NULL
ORDER BY i.item_name
"""

WINDOW_MOVERS_SQL = ITEMS_CTE + """
SELECT i.item_name,
       f.price AS old_price, f.recorded_at AS first_at,
       l.price AS new_price, l.recorded_at AS last_at
FROM items i
CROSS JOIN LATERAL (
  SELECT price, recorded_at FROM price_history h
  WHERE h.item_name = i.item_name
    AND h.recorded_at >= now() - make_interval(hours => %s)
  ORDER BY h.recorded_at ASC LIMIT 1
) f
CROSS JOIN LATERAL (
  SELECT price, recorded_at FROM price_history h
  WHERE h.item_name = i.item_name
  ORDER BY h.recorded_at DESC LIMIT 1
) l
WHERE i.item_name IS NOT NULL
ORDER BY i.item_name
"""

ITEM_HISTORY_RAW_SQL = """
SELECT recorded_at, price, bid, ask, volume
FROM price_history
WHERE item_name = %s AND recorded_at >= now() - make_interval(hours => %s)
ORDER BY recorded_at ASC
"""

ITEM_HISTORY_BINNED_SQL = """
SELECT date_bin(make_interval(hours => %s), recorded_at, '1970-01-01'::timestamptz) AS bin_start,
       avg(price) AS price,
       avg(bid)   AS bid,
       avg(ask)   AS ask
FROM price_history
WHERE item_name = %s AND recorded_at >= now() - make_interval(hours => %s)
GROUP BY bin_start
ORDER BY bin_start ASC
"""

ITEM_HOURLY_VOLUME_SQL = """
SELECT hour_start, qty
FROM price_volume_hourly
WHERE item_name = %s AND hour_start >= now() - make_interval(hours => %s)
ORDER BY hour_start ASC
"""


def get_home_market_data(window_hours: tuple[int, ...]) -> dict:
    """Satu koneksi: harga terakhir per item + harga awal/akhir tiap jendela (jam)."""
    with web_session() as cursor:
        cursor.execute(LATEST_PER_ITEM_SQL)
        latest_rows = fetch_dicts(cursor)
        movers_by_window = {}
        for hours in window_hours:
            cursor.execute(WINDOW_MOVERS_SQL, (hours,))
            movers_by_window[hours] = fetch_dicts(cursor)
    return {"latest": latest_rows, "movers": movers_by_window}


def get_items_latest() -> list[dict]:
    with web_session() as cursor:
        cursor.execute(LATEST_PER_ITEM_SQL)
        return fetch_dicts(cursor)


def get_item_history_raw(item_name: str, hours: int) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(ITEM_HISTORY_RAW_SQL, (item_name, hours))
        return fetch_dicts(cursor)


def get_item_history_binned(item_name: str, hours: int, bin_hours: int) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(ITEM_HISTORY_BINNED_SQL, (bin_hours, item_name, hours))
        return fetch_dicts(cursor)


def get_item_hourly_volume(item_name: str, hours: int) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(ITEM_HOURLY_VOLUME_SQL, (item_name, hours))
        return fetch_dicts(cursor)


# OHLC: open = harga pertama bin, close = harga terakhir bin.
ITEM_HISTORY_OHLC_SQL = """
SELECT date_bin(make_interval(hours => %s), recorded_at, '1970-01-01'::timestamptz) AS bin_start,
       (array_agg(price ORDER BY recorded_at ASC))[1]  AS open,
       max(price)                                       AS high,
       min(price)                                       AS low,
       (array_agg(price ORDER BY recorded_at DESC))[1] AS close,
       sum(volume)                                      AS volume
FROM price_history
WHERE item_name = %s AND recorded_at >= now() - make_interval(hours => %s)
GROUP BY bin_start
ORDER BY bin_start ASC
"""


def get_item_history_ohlc(item_name: str, hours: int, bin_hours: int) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(ITEM_HISTORY_OHLC_SQL, (bin_hours, item_name, hours))
        return fetch_dicts(cursor)
