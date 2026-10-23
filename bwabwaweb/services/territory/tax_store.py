# territory_tax_store.py

from __future__ import annotations

import logging
from datetime import datetime

import psycopg2
import psycopg2.extras
import psycopg2.pool

from services.db.local import (
    APP_DB_HOST,
    APP_DB_PORT,
    APP_DB_DBNAME,
    APP_DB_USER,
    APP_DB_PASSWORD,
)

log = logging.getLogger("WarEraBot.territory_tax_store")

SCAN_KEY_WAGE_GLOBAL = "wage_global"

# TTL cache tax rate (dipindah dari collector.py 28 Sep, biar
# country_routes bisa pakai tanpa import dari background worker).
TAX_RATE_TTL_HOURS = 24

POOL_MIN_CONN = 1
POOL_MAX_CONN = 10  # dijaga kecil, app_db max_connections=40 dipake bareng PostgREST

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            POOL_MIN_CONN, POOL_MAX_CONN,
            host=APP_DB_HOST,
            port=APP_DB_PORT,
            dbname=APP_DB_DBNAME,
            user=APP_DB_USER,
            password=APP_DB_PASSWORD,
            connect_timeout=10,
        )
        log.info(f"territory_tax_store: connection pool dibuat (min={POOL_MIN_CONN}, max={POOL_MAX_CONN}).")
    return _pool


def _pool_get_conn():
    return _get_pool().getconn()


def _pool_put_conn(conn) -> None:
    if conn is not None:
        try:
            _get_pool().putconn(conn)
        except Exception as exc:
            log.error(f"_pool_put_conn: gagal kembalikan koneksi ke pool — {exc}")


from contextlib import contextmanager

@contextmanager
def db_session(commit: bool = False):
    """Context manager koneksi pool tax_store.

    Get conn -> yield cursor -> commit (opsional) -> put conn (selalu).
    Caller WAJIB wrap dalam try/except (get_conn bisa raise).
    """
    conn = _pool_get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool_put_conn(conn)


# --- territory_scan_state (bookmark scan incremental) ---

def get_scan_state(scan_key: str = SCAN_KEY_WAGE_GLOBAL) -> dict | None:
    try:
        with db_session() as cur:
            cur.execute(
                "SELECT last_tx_id, last_created_at FROM territory_scan_state WHERE scan_key = %s",
                (scan_key,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"last_tx_id": row[0], "last_created_at": row[1].isoformat() if row[1] else None}
    except Exception as exc:
        log.error(f"get_scan_state({scan_key}): gagal — {exc}")
        return None


def save_scan_state(last_tx_id: str, last_created_at: str | None, scan_key: str = SCAN_KEY_WAGE_GLOBAL) -> None:
    try:
        with db_session(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO territory_scan_state (scan_key, last_tx_id, last_created_at, last_scanned_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (scan_key) DO UPDATE
                    SET last_tx_id      = EXCLUDED.last_tx_id,
                        last_created_at = EXCLUDED.last_created_at,
                        last_scanned_at = now()
                """,
                (scan_key, last_tx_id, last_created_at),
            )
    except Exception as exc:
        log.error(f"save_scan_state({scan_key}): gagal — {exc}")


# --- territory_wage_events (raw event per transaksi wage) ---

def ensure_wage_events_owner_column() -> bool:
    """Tambah kolom owner_citizenship_country_id kalau belum ada.

    DOKUMENTASI: user DB tidak punya izin DDL. DDL aktual manual sbg postgres:
      ALTER TABLE territory_wage_events
        ADD COLUMN IF NOT EXISTS owner_citizenship_country_id TEXT;
    """
    try:
        with db_session(commit=True) as cur:
            cur.execute(
                "ALTER TABLE territory_wage_events "
                "ADD COLUMN IF NOT EXISTS owner_citizenship_country_id TEXT"
            )
        return True
    except Exception as exc:
        log.error(f"ensure_wage_events_owner_column: gagal ({exc!r})")
        return False



def save_wage_events_batch(rows: list[dict]) -> bool:
    """Insert batch wage events. Return bool — wajib dicek sebelum save bookmark."""
    if not rows:
        return True
    try:
        values = [
            (
                r["tx_id"], r["created_at"], r.get("updated_at"), r["money"],
                r["seller_id"], r["buyer_id"],
                r.get("company_id"), r.get("match_method", "unresolved"),
                r.get("operating_region_id"), r.get("operating_country_id"),
                r.get("worker_citizenship_country_id"), r.get("is_foreign_worker"),
                r.get("owner_citizenship_country_id"),
                r.get("income_tax_rate"), r.get("gross_tax"),
                r.get("tax_to_operating_country"), r.get("tax_to_worker_country"),
                psycopg2.extras.Json(r["raw_payload"]) if r.get("raw_payload") is not None else None,
                r.get("enriched_at"),
            )
            for r in rows
        ]
        with db_session(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO territory_wage_events
                    (tx_id, created_at, updated_at, money, seller_id, buyer_id,
                     company_id, match_method, operating_region_id, operating_country_id,
                     worker_citizenship_country_id, is_foreign_worker,
                     owner_citizenship_country_id,
                     income_tax_rate, gross_tax, tax_to_operating_country, tax_to_worker_country,
                     raw_payload, enriched_at)
                VALUES %s
                ON CONFLICT (tx_id) DO NOTHING
                """,
                values,
            )
        return True
    except Exception as exc:
        log.error(f"save_wage_events_batch: gagal ({len(rows)} baris) — {exc}")
        return False


def get_unresolved_events(limit: int = 500) -> list[dict]:
    try:
        with db_session() as cur:
            cur.execute(
                """
                SELECT tx_id, created_at, money, seller_id, buyer_id
                FROM territory_wage_events
                WHERE match_method = 'unresolved'
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {"tx_id": r[0], "created_at": r[1].isoformat() if r[1] else None,
             "money": r[2], "seller_id": r[3], "buyer_id": r[4]}
            for r in rows
        ]
    except Exception as exc:
        log.error(f"get_unresolved_events: gagal — {exc}")
        return []
# --- territory_worker_snapshots (cache worker.getWorkers per company) ---

def get_cached_worker_snapshot(company_id: str) -> list[dict] | None:
    """None = belum cache. [] = cache tapi 0 worker."""
    try:
        with db_session() as cur:
            cur.execute(
                "SELECT 1 FROM territory_worker_scan_log "
                "WHERE company_id = %s AND scanned_at > now() - interval '5 hours' LIMIT 1",
                (company_id,),
            )
            if cur.fetchone() is None:
                return None  # belum pernah discan, atau cache udah lewat 5 jam

            cur.execute(
                "SELECT user_id, employer_id, wage, joined_at, raw_payload "
                "FROM territory_worker_snapshots WHERE company_id = %s",
                (company_id,),
            )
            rows = cur.fetchall()
        return [
            {"user_id": r[0], "employer_id": r[1], "wage": r[2],
             "joined_at": r[3].isoformat() if r[3] else None, "raw_payload": r[4]}
            for r in rows
        ]
    except Exception as exc:
        log.error(f"get_cached_worker_snapshot({company_id}): gagal — {exc}")
        return None


def save_worker_snapshot_batch(company_id: str, workers: list[dict]) -> None:
    """Replace worker 1 company + log scan."""
    try:
        with db_session(commit=True) as cur:
            if workers:
                values = [
                    (
                        company_id, w["user"], w["employer"], w["wage"], w["joinedAt"],
                        psycopg2.extras.Json(w),
                    )
                    for w in workers
                ]
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO territory_worker_snapshots
                        (company_id, user_id, employer_id, wage, joined_at, raw_payload)
                    VALUES %s
                    ON CONFLICT (company_id, user_id) DO UPDATE
                        SET employer_id = EXCLUDED.employer_id,
                            wage        = EXCLUDED.wage,
                            joined_at   = EXCLUDED.joined_at,
                            raw_payload = EXCLUDED.raw_payload,
                            fetched_at  = now()
                    """,
                    values,
                )

            cur.execute(
                """
                INSERT INTO territory_worker_scan_log (company_id, scanned_at)
                VALUES (%s, now())
                ON CONFLICT (company_id) DO UPDATE SET scanned_at = now()
                """,
                (company_id,),
            )
    except Exception as exc:
        log.error(f"save_worker_snapshot_batch({company_id}): gagal — {exc}")


# --- territory_buyer_scan_state (TTL refresh company_index per buyer, 4-6 jam) ---

def get_buyer_last_scan(buyer_id: str) -> datetime | None:
    try:
        with db_session() as cur:
            cur.execute(
                "SELECT last_scan_at FROM territory_buyer_scan_state WHERE buyer_id = %s",
                (buyer_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:
        log.error(f"get_buyer_last_scan({buyer_id}): gagal — {exc}")
        return None


def save_buyer_scan_state(buyer_id: str) -> None:
    try:
        with db_session(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO territory_buyer_scan_state (buyer_id, last_scan_at)
                VALUES (%s, now())
                ON CONFLICT (buyer_id) DO UPDATE SET last_scan_at = now()
                """,
                (buyer_id,),
            )
    except Exception as exc:
        log.error(f"save_buyer_scan_state({buyer_id}): gagal — {exc}")


# --- territory_worker_citizenship_cache (TTL 30 hari) ---

def get_citizenship_cached(seller_ids: list[str], ttl_days: int) -> dict[str, str]:
    if not seller_ids:
        return {}
    try:
        with db_session() as cur:
            cur.execute(
                """
                SELECT seller_id, country_id FROM territory_worker_citizenship_cache
                WHERE seller_id = ANY(%s) AND fetched_at > now() - (%s || ' days')::interval
                """,
                (seller_ids, ttl_days),
            )
            rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception as exc:
        log.error(f"get_citizenship_cached: gagal — {exc}")
        return {}


def upsert_citizenship_batch(rows: list[dict]) -> None:
    if not rows:
        return
    try:
        values = [(r["seller_id"], r["country_id"]) for r in rows]
        with db_session(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO territory_worker_citizenship_cache (seller_id, country_id, fetched_at)
                VALUES %s
                ON CONFLICT (seller_id) DO UPDATE
                    SET country_id = EXCLUDED.country_id, fetched_at = now()
                """,
                values,
                template="(%s, %s, now())",
            )
    except Exception as exc:
        log.error(f"upsert_citizenship_batch: gagal ({len(rows)} baris) — {exc}")



# --- backfill owner_citizenship_country_id ---

def get_buyers_missing_owner_citizenship(limit: int = 500) -> list[str]:
    """Distinct buyer_id yang company_id NOT NULL tapi owner_citizenship NULL."""
    try:
        with db_session() as cur:
            cur.execute(
                """
                SELECT DISTINCT buyer_id FROM territory_wage_events
                WHERE company_id IS NOT NULL
                  AND owner_citizenship_country_id IS NULL
                  AND buyer_id IS NOT NULL AND buyer_id <> ''
                LIMIT %s
                """,
                (limit,),
            )
            return [r[0] for r in cur.fetchall()]
    except Exception as exc:
        log.error(f"get_buyers_missing_owner_citizenship: gagal ({exc!r})")
        return []


def update_owner_citizenship_batch(rows: list[dict]) -> int:
    """Update owner_citizenship_country_id per buyer_id. Return jumlah baris."""
    if not rows:
        return 0
    try:
        with db_session(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                UPDATE territory_wage_events AS e SET
                    owner_citizenship_country_id = v.country_id
                FROM (VALUES %s) AS v(buyer_id, country_id)
                WHERE e.buyer_id = v.buyer_id
                  AND e.owner_citizenship_country_id IS NULL
                """,
                [(r["buyer_id"], r["country_id"]) for r in rows],
            )
            return cur.rowcount
    except Exception as exc:
        log.error(f"update_owner_citizenship_batch: gagal ({exc!r})")
        return 0


# --- territory_seller_last_wage ---

def upsert_seller_last_wage(rows: list[dict]) -> None:
    if not rows:
        return
    try:
        values = [
            (r["seller_id"], r["buyer_id"], r["company_id"], r["income_tax_rate"], r["created_at"])
            for r in rows
        ]
        with db_session(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO seller_last_wage (seller_id, buyer_id, company_id, income_tax_rate, created_at)
                VALUES %s
                ON CONFLICT (seller_id) DO UPDATE
                SET buyer_id = EXCLUDED.buyer_id,
                    company_id = EXCLUDED.company_id,
                    income_tax_rate = EXCLUDED.income_tax_rate,
                    created_at = EXCLUDED.created_at
                WHERE EXCLUDED.created_at >= seller_last_wage.created_at
                """,
                values,
                template="(%s, %s, %s, %s, %s)",
            )
    except Exception as exc:
        log.error(f"upsert_seller_last_wage: gagal ({len(rows)} baris) — {exc}")


def get_seller_last_wage(seller_id: str) -> dict | None:
    try:
        with db_session() as cur:
            cur.execute(
                """
                SELECT seller_id, buyer_id, company_id, income_tax_rate, created_at
                FROM seller_last_wage
                WHERE seller_id = %s
                """,
                (seller_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["seller_id", "buyer_id", "company_id", "income_tax_rate", "created_at"]
            return dict(zip(cols, row))
    except Exception as exc:
        log.error(f"get_seller_last_wage: gagal ({seller_id}) — {exc}")
        return None


# --- territory_wage_events retention purge (dump-to-file lalu delete) ---

import gzip
import os

DATA_EXPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_exports")


def purge_old_wage_events(retention_days: int) -> tuple[bool, int]:
    """Dump baris territory_wage_events yg lebih tua dari retention_days ke
    file CSV.gz (satu transaksi bareng DELETE, snapshot konsisten), lalu hapus
    dari tabel. Return (ok, jumlah_baris_terhapus). Kalau dump atau delete
    gagal, transaksi di-rollback -- tidak ada data hilang tanpa backup."""
    os.makedirs(DATA_EXPORTS_DIR, exist_ok=True)
    label = datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_path = os.path.join(DATA_EXPORTS_DIR, f"territory_wage_events_purged_{label}.csv.gz")
    retention_days = int(retention_days)

    try:
        with db_session(commit=True) as cur:
            cur.execute(
                "SELECT COUNT(*) FROM territory_wage_events WHERE created_at < now() - make_interval(days => %s)",
                (retention_days,),
            )
            row_count = cur.fetchone()[0]

            if row_count == 0:
                log.info(f"purge_old_wage_events: tidak ada baris >{retention_days} hari, skip.")
                return True, 0

            with gzip.open(dump_path, "wt", newline="") as f:
                cur.copy_expert(
                    f"""
                    COPY (
                        SELECT * FROM territory_wage_events
                        WHERE created_at < now() - make_interval(days => {retention_days})
                    ) TO STDOUT WITH CSV HEADER
                    """,
                    f,
                )

            cur.execute(
                "DELETE FROM territory_wage_events WHERE created_at < now() - make_interval(days => %s)",
                (retention_days,),
            )
            deleted = cur.rowcount

        log.info(
            f"purge_old_wage_events: {deleted} baris di-dump ke {dump_path} lalu dihapus "
            f"(retensi {retention_days} hari)."
        )
        return True, deleted
    except Exception as exc:
        if os.path.exists(dump_path):
            try:
                os.remove(dump_path)
            except Exception:
                pass
        log.error(f"purge_old_wage_events: gagal ({exc!r}), transaksi di-rollback, dump dihapus.")
        return False, 0

# --- territory_country_tax_rate_cache (TTL 24 jam) ---

def get_tax_rate_cached(country_ids: list[str], ttl_hours: int) -> dict[str, dict]:
    if not country_ids:
        return {}
    try:
        with db_session() as cur:
            cur.execute(
                """
                SELECT country_id, income_rate, market_rate, selfwork_rate
                FROM territory_country_tax_rate_cache
                WHERE country_id = ANY(%s) AND fetched_at > now() - (%s || ' hours')::interval
                """,
                (country_ids, ttl_hours),
            )
            rows = cur.fetchall()
        return {r[0]: {"income_rate": r[1], "market_rate": r[2], "selfwork_rate": r[3]} for r in rows}
    except Exception as exc:
        log.error(f"get_tax_rate_cached: gagal — {exc}")
        return {}


def upsert_tax_rate_batch(rows: list[dict]) -> None:
    if not rows:
        return
    try:
        values = [
            (r["country_id"], r.get("income_rate"), r.get("market_rate"), r.get("selfwork_rate"))
            for r in rows
        ]
        with db_session(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO territory_country_tax_rate_cache
                    (country_id, income_rate, market_rate, selfwork_rate, fetched_at)
                VALUES %s
                ON CONFLICT (country_id) DO UPDATE
                    SET income_rate   = EXCLUDED.income_rate,
                        market_rate   = EXCLUDED.market_rate,
                        selfwork_rate = EXCLUDED.selfwork_rate,
                        fetched_at    = now()
                """,
                values,
                template="(%s, %s, %s, %s, now())",
            )
    except Exception as exc:
        log.error(f"upsert_tax_rate_batch: gagal ({len(rows)} baris) — {exc}")


# --- query agregasi buat territory_routes.py (tab Territory di dashboard) ---

def get_country_tax_summary(country_id: str, since_dt: datetime, until_dt: datetime) -> dict:
    """Ringkasan pajak: collected + sent_to_citizens_abroad."""
    try:
        with db_session() as cur:
            cur.execute(
                """
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
                """,
                (country_id, since_dt, until_dt),
            )
            collected_row = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*) AS tx_count,
                    COALESCE(SUM(tax_to_worker_country), 0) AS tax_sent
                FROM territory_wage_events
                WHERE worker_citizenship_country_id = %s
                  AND operating_country_id IS DISTINCT FROM %s
                  AND created_at >= %s
                  AND created_at < %s
                  AND income_tax_rate IS NOT NULL
                """,
                (country_id, country_id, since_dt, until_dt),
            )
            sent_row = cur.fetchone()

        return {
            "collected": {
                "tx_count": collected_row[0],
                "gross_tax_total": float(collected_row[1]),
                "tax_collected": float(collected_row[2]),
                "wage_volume": float(collected_row[3]),
                "foreign_tx_count": collected_row[4],
                "foreign_gross_tax": float(collected_row[5]),
                "domestic_tx_count": collected_row[6],
                "domestic_gross_tax": float(collected_row[7]),
                "company_count": collected_row[8],
            },
            "sent_to_citizens_abroad": {
                "tx_count": sent_row[0],
                "tax_sent": float(sent_row[1]),
            },
        }
    except Exception as exc:
        log.error(f"get_country_tax_summary({country_id}): gagal — {exc}")
        return {}


def get_country_tax_daily(country_id: str, since_dt: datetime, until_dt: datetime) -> list[dict]:
    try:
        with db_session() as cur:
            cur.execute(
                """
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
                """,
                (country_id, since_dt, until_dt),
            )
            rows = cur.fetchall()
        return [
            {
                "day": r[0].date().isoformat() if r[0] else None,
                "tx_count": r[1],
                "gross_tax_total": float(r[2]),
                "tax_collected": float(r[3]),
            }
            for r in rows
        ]
    except Exception as exc:
        log.error(f"get_country_tax_daily({country_id}): gagal — {exc}")
        return []


def get_country_tax_events(country_id: str, limit: int = 50) -> list[dict]:
    try:
        with db_session() as cur:
            cur.execute(
                """
                SELECT tx_id, created_at, seller_id, buyer_id, company_id,
                       money, income_tax_rate, gross_tax, tax_to_operating_country,
                       tax_to_worker_country, is_foreign_worker, worker_citizenship_country_id
                FROM territory_wage_events
                WHERE operating_country_id = %s
                  AND income_tax_rate IS NOT NULL
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (country_id, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "tx_id": r[0],
                "created_at": r[1].isoformat() if r[1] else None,
                "seller_id": r[2],
                "buyer_id": r[3],
                "company_id": r[4],
                "money": float(r[5]) if r[5] is not None else None,
                "income_tax_rate": float(r[6]) if r[6] is not None else None,
                "gross_tax": float(r[7]) if r[7] is not None else None,
                "tax_to_operating_country": float(r[8]) if r[8] is not None else None,
                "tax_to_worker_country": float(r[9]) if r[9] is not None else None,
                "is_foreign_worker": r[10],
                "worker_citizenship_country_id": r[11],
            }
            for r in rows
        ]
    except Exception as exc:
        log.error(f"get_country_tax_events({country_id}): gagal — {exc}")
        return []


def get_top_tax_countries(since_dt: datetime, until_dt: datetime, limit: int = 10) -> list[dict]:
    try:
        with db_session() as cur:
            cur.execute(
                """
                SELECT
                    operating_country_id,
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
                """,
                (since_dt, until_dt, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "country_id": r[0],
                "tx_count": r[1],
                "gross_tax_total": float(r[2]),
                "tax_collected": float(r[3]),
            }
            for r in rows
        ]
    except Exception as exc:
        log.error(f"get_top_tax_countries: gagal — {exc}")
        return []


_DATE_CAST = "(created_at AT TIME ZONE 'UTC')::date"


def recalculate_daily_wage_rollup(dates: list[str]) -> bool:
    if not dates:
        return True
    ok = True
    for d in dates:
        try:
            with db_session(commit=True) as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*), AVG(money), MAX(money), MIN(money),
                           AVG(money - gross_tax), MAX(money - gross_tax), MIN(money - gross_tax)
                    FROM territory_wage_events
                    WHERE company_id IS NOT NULL
                      AND income_tax_rate IS NOT NULL
                      AND gross_tax IS NOT NULL
                      AND {_DATE_CAST} = %s
                    """,
                    (d,),
                )
                row = cur.fetchone()
                if not row or row[0] == 0:
                    continue
                count, avg_g, max_g, min_g, avg_n, max_n, min_n = row
                cur.execute(
                    """
                    INSERT INTO territory_daily_wage_rollup
                        (date, event_count, avg_gross_wage, max_gross_wage, min_gross_wage,
                         avg_net_wage, max_net_wage, min_net_wage, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (date) DO UPDATE SET
                        event_count = EXCLUDED.event_count,
                        avg_gross_wage = EXCLUDED.avg_gross_wage,
                        max_gross_wage = EXCLUDED.max_gross_wage,
                        min_gross_wage = EXCLUDED.min_gross_wage,
                        avg_net_wage = EXCLUDED.avg_net_wage,
                        max_net_wage = EXCLUDED.max_net_wage,
                        min_net_wage = EXCLUDED.min_net_wage,
                        updated_at = now()
                    """,
                    (d, count, avg_g, max_g, min_g, avg_n, max_n, min_n),
                )
        except Exception as exc:
            log.error(f"recalculate_daily_wage_rollup: gagal utk tanggal {d} ({exc!r})")
            ok = False
    return ok


_RATE_CTE = f"""
    WITH day_pairs AS (
        SELECT DISTINCT ON (company_id, seller_id)
            company_id, seller_id, income_tax_rate
        FROM territory_wage_events
        WHERE company_id IS NOT NULL
          AND income_tax_rate IS NOT NULL
          AND {_DATE_CAST} = %s
        ORDER BY company_id, seller_id, created_at DESC
    ),
    rates AS (
        SELECT dp.company_id, dp.seller_id AS user_id,
               tws.wage AS gross_rate,
               tws.wage * (1 - dp.income_tax_rate / 100.0) AS net_rate
        FROM day_pairs dp
        JOIN territory_worker_snapshots tws
            ON tws.company_id = dp.company_id AND tws.user_id = dp.seller_id
    )
"""


def get_daily_wage_summary(date_str: str) -> dict | None:
    try:
        with db_session() as cur:
            cur.execute(
                _RATE_CTE + "SELECT COUNT(*), AVG(gross_rate), AVG(net_rate) FROM rates",
                (date_str,),
            )
            row = cur.fetchone()
            if not row or row[0] == 0:
                return None
            event_count, avg_gross, avg_net = row

            cur.execute(
                _RATE_CTE + """
                , mx AS (SELECT MAX(gross_rate) AS v FROM rates)
                SELECT company_id, user_id, gross_rate FROM rates, mx WHERE gross_rate = mx.v
                """,
                (date_str,),
            )
            top_gross = [{"company_id": r[0], "seller_id": r[1], "value": float(r[2])} for r in cur.fetchall()]

            cur.execute(
                _RATE_CTE + """
                , mx AS (SELECT MAX(net_rate) AS v FROM rates)
                SELECT company_id, user_id, net_rate FROM rates, mx WHERE net_rate = mx.v
                """,
                (date_str,),
            )
            top_net = [{"company_id": r[0], "seller_id": r[1], "value": float(r[2])} for r in cur.fetchall()]
    except Exception as exc:
        log.error(f"get_daily_wage_summary({date_str}): gagal ({exc!r})")
        return None
    return {
        "event_count": event_count,
        "avg_gross_wage": float(avg_gross) if avg_gross is not None else None,
        "avg_net_wage": float(avg_net) if avg_net is not None else None,
        "top_gross": top_gross,
        "top_net": top_net,
    }
