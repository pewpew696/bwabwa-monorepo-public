# fiscal_breakdown_rollup.py
"""Agregasi breakdown Fiscal Monitor: per region, owner country, item.

Dibaca dari territory_wage_events (+ JOIN company_index buat item_code),
ditulis ke territory_hourly_country_fiscal_breakdown. Dipakai drilldown country
di /territory/tax-calc/{country_id}. Tanpa fastapi."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("WarEraBot.fiscal_breakdown_rollup")


def _db_session():
    # Lazy import: modul tetap bisa di-test tanpa psycopg2.
    from services.territory.tax_store import db_session

    return db_session


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS territory_hourly_country_fiscal_breakdown (
    hour TIMESTAMPTZ NOT NULL,
    country_id TEXT NOT NULL,
    region_id TEXT NOT NULL DEFAULT '',
    owner_country_id TEXT NOT NULL DEFAULT '',
    item_code TEXT NOT NULL DEFAULT '',
    tax_income NUMERIC NOT NULL DEFAULT 0,
    wages_paid NUMERIC NOT NULL DEFAULT 0,
    transactions INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (hour, country_id, region_id, owner_country_id, item_code)
)
"""


def ensure_breakdown_table() -> bool:
    """Pastikan tabel breakdown ada. Pola sama ensure_fiscal_table:
    cek via SELECT dulu (tanpa izin CREATE), baru coba CREATE."""
    try:
        with _db_session()() as cur:
            cur.execute("SELECT 1 FROM territory_hourly_country_fiscal_breakdown LIMIT 1")
        return True
    except Exception:
        pass
    try:
        with _db_session()(commit=True) as cur:
            cur.execute(_CREATE_TABLE_SQL)
        return True
    except Exception as exc:
        log.error(f"ensure_breakdown_table: gagal ({exc!r})")
        return False


# Agregat per (jam, negara, region, owner_country, item).
# item_code dari company_index (LEFT JOIN; NULL -> '').
_AGGREGATE_SQL = """
SELECT
    date_trunc('hour', e.created_at) AS hour,
    e.operating_country_id AS country_id,
    COALESCE(e.operating_region_id, '') AS region_id,
    COALESCE(e.owner_citizenship_country_id, '') AS owner_country_id,
    COALESCE(ci.item_code, '') AS item_code,
    COALESCE(SUM(e.tax_to_operating_country), 0) AS tax_income,
    COALESCE(SUM(e.money), 0) AS wages_paid,
    COUNT(*) AS transactions
FROM territory_wage_events e
LEFT JOIN company_index ci ON ci.company_id = e.company_id
WHERE e.company_id IS NOT NULL
  AND e.gross_tax IS NOT NULL
  AND e.operating_country_id IS NOT NULL
  AND e.created_at >= %s AND e.created_at < %s
GROUP BY 1, 2, 3, 4, 5
"""

_UPSERT_SQL = """
INSERT INTO territory_hourly_country_fiscal_breakdown
    (hour, country_id, region_id, owner_country_id, item_code,
     tax_income, wages_paid, transactions)
VALUES %s
ON CONFLICT (hour, country_id, region_id, owner_country_id, item_code)
DO UPDATE SET
    tax_income = EXCLUDED.tax_income,
    wages_paid = EXCLUDED.wages_paid,
    transactions = EXCLUDED.transactions,
    updated_at = now()
"""


def recalculate_hourly_fiscal_breakdown(hours: list[datetime]) -> bool:
    """Hitung ulang breakdown untuk daftar jam (UTC, hour-aligned).

    Idempotent — aman dipanggil ulang. Return False kalau gagal.
    """
    if not hours:
        return True
    if not ensure_breakdown_table():
        return False
    norm = sorted({h.replace(minute=0, second=0, microsecond=0) for h in hours})
    norm = [h if h.tzinfo else h.replace(tzinfo=timezone.utc) for h in norm]
    try:
        import psycopg2.extras

        # Range untuk index: dari jam paling awal sampai 1 jam setelah jam paling akhir.
        since = min(norm)
        until = max(norm) + timedelta(hours=1)
        with _db_session()(commit=True) as cur:
            cur.execute(_AGGREGATE_SQL, (since, until))
            rows = cur.fetchall()
            if not rows:
                return True
            values = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows]
            psycopg2.extras.execute_values(cur, _UPSERT_SQL, values)
        return True
    except Exception as exc:
        log.error(f"recalculate_hourly_fiscal_breakdown: gagal ({exc!r})")
        return False
