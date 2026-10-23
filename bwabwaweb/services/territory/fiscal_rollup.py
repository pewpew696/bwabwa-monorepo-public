# fiscal_rollup.py
"""Agregasi pajak per-country per-jam buat dashboard Fiscal Monitor.

Dibaca dari territory_wage_events (data collector yang sudah jalan),
ditulis ke territory_hourly_country_fiscal. Dashboard webapp baca tabel
kecil ini, bukan 5.6Jt baris mentah.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("WarEraBot.fiscal_rollup")


def _db_session():
    # Lazy import: modul tetap bisa di-test tanpa psycopg2.
    from services.territory.tax_store import db_session

    return db_session

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS territory_hourly_country_fiscal (
    hour TIMESTAMPTZ NOT NULL,
    country_id TEXT NOT NULL,
    tax_income NUMERIC NOT NULL DEFAULT 0,
    wages_paid NUMERIC NOT NULL DEFAULT 0,
    transactions INTEGER NOT NULL DEFAULT 0,
    avg_tax_rate NUMERIC,
    foreign_tax NUMERIC NOT NULL DEFAULT 0,
    domestic_tax NUMERIC NOT NULL DEFAULT 0,
    tax_to_worker_country NUMERIC NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (hour, country_id)
)
"""

def ensure_fiscal_table() -> bool:
    """Pastikan tabel rollup ada. Return True kalau tabel bisa dipakai.

    Cek dulu via SELECT (tanpa butuh izin CREATE); baru coba CREATE kalau
    belum ada. User DB webapp tidak punya izin CREATE, jadi DDL manual
    via postgres tetap didukung.
    """
    # 1. tabel sudah ada dan bisa dibaca? -> langsung True.
    try:
        with _db_session()() as cur:
            cur.execute("SELECT 1 FROM territory_hourly_country_fiscal LIMIT 1")
        return True
    except Exception:
        pass  # belum ada / tidak bisa baca -> coba buat
    # 2. coba buat (butuh izin CREATE; gagal -> False).
    try:
        with _db_session()(commit=True) as cur:
            cur.execute(_CREATE_TABLE_SQL)
        return True
    except Exception as exc:
        log.error(f"ensure_fiscal_table: gagal ({exc!r})")
        return False


_AGGREGATE_SQL = """
SELECT
    date_trunc('hour', created_at) AS hour,
    operating_country_id AS country_id,
    COALESCE(SUM(tax_to_operating_country), 0) AS tax_income,
    COALESCE(SUM(money), 0) AS wages_paid,
    COUNT(*) AS transactions,
    AVG(income_tax_rate) AS avg_tax_rate,
    COALESCE(SUM(tax_to_operating_country) FILTER (WHERE is_foreign_worker IS TRUE), 0)
        AS foreign_tax,
    COALESCE(SUM(tax_to_operating_country) FILTER (WHERE is_foreign_worker IS FALSE), 0)
        AS domestic_tax,
    COALESCE(SUM(tax_to_worker_country), 0) AS tax_to_worker_country
FROM territory_wage_events
WHERE company_id IS NOT NULL
  AND gross_tax IS NOT NULL
  AND income_tax_rate IS NOT NULL
  AND operating_country_id IS NOT NULL
  AND created_at >= %s AND created_at < %s
GROUP BY 1, 2
"""

_UPSERT_SQL = """
INSERT INTO territory_hourly_country_fiscal
    (hour, country_id, tax_income, wages_paid, transactions, avg_tax_rate,
     foreign_tax, domestic_tax, tax_to_worker_country)
VALUES %s
ON CONFLICT (hour, country_id) DO UPDATE SET
    tax_income = EXCLUDED.tax_income,
    wages_paid = EXCLUDED.wages_paid,
    transactions = EXCLUDED.transactions,
    avg_tax_rate = EXCLUDED.avg_tax_rate,
    foreign_tax = EXCLUDED.foreign_tax,
    domestic_tax = EXCLUDED.domestic_tax,
    tax_to_worker_country = EXCLUDED.tax_to_worker_country,
    updated_at = now()
"""


def recalculate_hourly_fiscal(hours: list[datetime]) -> bool:
    """Hitung ulang agregasi untuk daftar jam (UTC, hour-aligned).

    Pola sama recalculate_daily_wage_rollup: aggregate dari events mentah,
    upsert ke tabel rollup. Idempotent — aman dipanggil ulang.
    """
    if not hours:
        return True
    if not ensure_fiscal_table():
        return False
    # Normalisasi ke hour-aligned UTC.
    norm = sorted({h.replace(minute=0, second=0, microsecond=0) for h in hours})
    # Pastikan timezone-aware UTC (banding string ISO di bawah).
    norm = [
        h if h.tzinfo else h.replace(tzinfo=timezone.utc)
        for h in norm
    ]
    ok = True
    try:
        import psycopg2.extras

        with _db_session()(commit=True) as cur:
            since = min(norm)
            until = max(norm) + timedelta(hours=1)
            cur.execute(_AGGREGATE_SQL, (since, until))
            rows = cur.fetchall()
            if not rows:
                return True
            values = [
                (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8])
                for r in rows
            ]
            psycopg2.extras.execute_values(cur, _UPSERT_SQL, values)
    except Exception as exc:
        log.error(f"recalculate_hourly_fiscal: gagal ({exc!r})")
        ok = False
    return ok


def touched_hours_from_rows(rows: list[dict]) -> list[datetime]:
    """Ambil jam-jam unik (UTC) dari batch event collector."""
    hours = set()
    for r in rows:
        if not r.get("company_id") or r.get("gross_tax") is None:
            continue
        created = r.get("created_at")
        if not created:
            continue
        try:
            # Format ISO dari API, mis. "2026-10-09T05:23:11.000Z".
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            hours.add(dt.replace(minute=0, second=0, microsecond=0))
        except (ValueError, TypeError, AttributeError):
            continue
    return sorted(hours)
