# spy_cache_store.py

from __future__ import annotations

import logging

import psycopg2
import psycopg2.extras

from services.db.local import local_session, local_session_raw

log = logging.getLogger("WarEraBot.spy_cache_store")

_COMPANY_UPSERT_CHUNK_SIZE = 500


# --- company_index ---

def upsert_companies_batch(rows: list[dict]) -> int:
    """Upsert batch company, return jumlah ter-upsert."""
    if not rows:
        return 0

    upserted = 0
    try:
        with local_session_raw() as conn:
            for i in range(0, len(rows), _COMPANY_UPSERT_CHUNK_SIZE):
                chunk = rows[i:i + _COMPANY_UPSERT_CHUNK_SIZE]
                values = [
                    (
                        r["company_id"], r.get("owner_id", ""), r.get("region_id", ""),
                        r.get("item_code", ""), r.get("name", ""),
                        int(r.get("worker_count") or 0), float(r.get("production_rate") or 0),
                        float(r.get("estimated_value") or 0), int(r.get("ae_level") or 0),
                        bool(r.get("is_full") or False),
                    )
                    for r in chunk
                ]
                try:
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(
                            cur,
                            """
                            INSERT INTO company_index
                            (company_id, owner_id, region_id, item_code, name,
                             worker_count, production_rate, estimated_value, ae_level,
                             is_full, updated_at)
                            VALUES %s
                            ON CONFLICT (company_id) DO UPDATE
                                SET owner_id        = EXCLUDED.owner_id,
                                    region_id       = EXCLUDED.region_id,
                                    item_code       = EXCLUDED.item_code,
                                    name            = EXCLUDED.name,
                                    worker_count    = EXCLUDED.worker_count,
                                    production_rate = EXCLUDED.production_rate,
                                    estimated_value = EXCLUDED.estimated_value,
                                    ae_level        = EXCLUDED.ae_level,
                                    is_full         = EXCLUDED.is_full,
                                    updated_at      = now()
                            """,
                            values,
                            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())",
                        )
                    conn.commit()
                    upserted += len(chunk)
                except Exception as exc:
                    conn.rollback()
                    log.error(
                        f"upsert_companies_batch: chunk {i}-{i + len(chunk)} gagal "
                        f"({len(chunk)} baris hilang dari upsert ini) — {exc}"
                    )
    except Exception as exc:
        log.error(f"upsert_companies_batch: gagal connect — {exc}")
        return 0

    if upserted < len(rows):
        log.warning(f"upsert_companies_batch: {upserted}/{len(rows)} baris ter-upsert.")
    return upserted


def get_companies_by_owner(owner_id: str) -> list[dict]:
    """Semua company milik owner_id."""
    try:
        with local_session() as cur:
            cur.execute(
                """
                SELECT company_id, region_id, item_code, worker_count, owner_id,
                       name, production_rate, estimated_value, ae_level, is_full, updated_at
                FROM company_index
                WHERE owner_id = %s
                """,
                (owner_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "company_id": r[0], "region_id": r[1], "item_code": r[2],
                "worker_count": r[3], "owner_id": r[4], "name": r[5],
                "production_rate": r[6], "estimated_value": r[7], "ae_level": r[8],
                "is_full": r[9], "updated_at": r[10].isoformat() if r[10] else None,
            }
            for r in rows
        ]
    except Exception as exc:
        log.error(f"get_companies_by_owner({owner_id}): gagal — {exc}")
        return []


def get_company_region(company_id: str) -> str | None:
    """region_id buat 1 company_id — dipake territory_tax_collector."""
    try:
        with local_session() as cur:
            cur.execute(
                "SELECT region_id FROM company_index WHERE company_id = %s LIMIT 1",
                (company_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:
        log.error(f"get_company_region({company_id}): gagal — {exc}")
        return None


def get_companies_by_regions(region_ids: list[str]) -> list[dict]:
    """Semua company di region_ids (dari full-scan)."""
    if not region_ids:
        return []
    try:
        with local_session() as cur:
            cur.execute(
                """
                SELECT company_id, region_id, item_code, worker_count, owner_id,
                       name, production_rate, estimated_value, ae_level, is_full, updated_at
                FROM company_index
                WHERE region_id = ANY(%s)
                """,
                (list(region_ids),),
            )
            rows = cur.fetchall()
        return [
            {
                "company_id": r[0], "region_id": r[1], "item_code": r[2],
                "worker_count": r[3], "owner_id": r[4], "name": r[5],
                "production_rate": r[6], "estimated_value": r[7], "ae_level": r[8],
                "is_full": r[9], "updated_at": r[10].isoformat() if r[10] else None,
            }
            for r in rows
        ]
    except Exception as exc:
        log.error(f"get_companies_by_regions: gagal — {exc}")
        return []


def get_stale_company_ids(stale_cutoff_iso: str, limit: int = 500) -> list[str]:
    """Company updated_at < cutoff."""
    try:
        with local_session() as cur:
            cur.execute(
                """
                SELECT company_id FROM company_index
                WHERE updated_at < %s
                ORDER BY updated_at ASC
                LIMIT %s
                """,
                (stale_cutoff_iso, limit),
            )
            rows = cur.fetchall()
        return [r[0] for r in rows]
    except Exception as exc:
        log.error(f"get_stale_company_ids: gagal — {exc}")
        return []


def delete_companies_batch(company_ids: list[str]) -> int:
    """Hapus company yang confirmed dibongkar."""
    if not company_ids:
        return 0
    try:
        with local_session(commit=True) as cur:
            cur.execute(
                "DELETE FROM company_index WHERE company_id = ANY(%s)",
                (list(company_ids),),
            )
            return cur.rowcount
    except Exception as exc:
        log.error(f"delete_companies_batch: gagal ({len(company_ids)} id) — {exc}")
        return 0


def get_company_count() -> int:
    """Jumlah company di company_index."""
    try:
        with local_session() as cur:
            cur.execute("SELECT COUNT(*) FROM company_index")
            return cur.fetchone()[0]
    except Exception as exc:
        log.error(f"get_company_count: gagal — {exc}")
        return -1


def get_company_index_stats(one_hour_ago_iso: str, one_day_ago_iso: str) -> dict:
    """Statistik company_index buat xspy scan."""
    try:
        with local_session() as cur:
            cur.execute("SELECT COUNT(*) FROM company_index")
            total = cur.fetchone()[0]

            cur.execute("SELECT MAX(updated_at) FROM company_index")
            last_updated_row = cur.fetchone()
            last_updated = last_updated_row[0].isoformat() if last_updated_row and last_updated_row[0] else None

            cur.execute("SELECT COUNT(*) FROM company_index WHERE updated_at >= %s", (one_hour_ago_iso,))
            last_hour_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM company_index WHERE updated_at >= %s", (one_day_ago_iso,))
            last_day_count = cur.fetchone()[0]

        return {
            "total": total, "last_updated": last_updated,
            "last_hour_count": last_hour_count, "last_day_count": last_day_count,
        }
    except Exception as exc:
        log.error(f"get_company_index_stats: gagal — {exc}")
        return {"total": 0, "last_updated": None, "last_hour_count": 0, "last_day_count": 0}


# --- inventory_cache ---

def get_cached_inventory(user_id: str) -> dict | None:
    """Baca 1 baris inventory_cache, None kalau kosong."""
    try:
        with local_session() as cur:
            cur.execute(
                """
                SELECT inventory, rarity_breakdown, total_items, pages_fetched,
                       capped, refreshed_at
                FROM inventory_cache
                WHERE user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "inventory": row[0] or {},
            "rarity_breakdown": row[1] or {},
            "total_items": row[2] or 0,
            "pages_fetched": row[3] or 0,
            "capped": bool(row[4]),
            "refreshed_at": row[5].isoformat() if row[5] else None,
        }
    except Exception as exc:
        log.error(f"get_cached_inventory({user_id}): gagal — {exc}")
        return None


def upsert_inventory_cache(user_id: str, row: dict) -> None:
    """Simpan/update 1 baris inventory_cache."""
    try:
        with local_session(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO inventory_cache
                (user_id, inventory, rarity_breakdown, total_items,
                 pages_fetched, capped, refreshed_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (user_id) DO UPDATE
                SET inventory        = EXCLUDED.inventory,
                    rarity_breakdown = EXCLUDED.rarity_breakdown,
                    total_items      = EXCLUDED.total_items,
                    pages_fetched    = EXCLUDED.pages_fetched,
                    capped           = EXCLUDED.capped,
                    refreshed_at     = now()
                """,
                (
                    user_id,
                    psycopg2.extras.Json(row.get("inventory") or {}),
                    psycopg2.extras.Json(row.get("rarity_breakdown") or {}),
                    int(row.get("total_items") or 0),
                    int(row.get("pages_fetched") or 0),
                    bool(row.get("capped") or False),
                ),
            )
    except Exception as exc:
        log.error(f"upsert_inventory_cache({user_id}): gagal — {exc}")


def get_company_owner(company_id: str) -> str | None:
    """company_id -> owner_id, dari company_index."""
    try:
        with local_session() as cur:
            cur.execute(
                "SELECT owner_id FROM company_index WHERE company_id = %s",
                (company_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:
        log.error(f"get_company_owner({company_id}): gagal — {exc}")
        return None


def get_companies_owners_batch(company_ids: list[str]) -> dict[str, str]:
    """Versi batch get_company_owner — buat banyak company_id sekaligus."""
    if not company_ids:
        return {}
    try:
        with local_session() as cur:
            cur.execute(
                "SELECT company_id, owner_id FROM company_index WHERE company_id = ANY(%s)",
                (company_ids,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}
    except Exception as exc:
        log.error(f"get_companies_owners_batch: gagal — {exc}")
        return {}


# --- player_activity (lapisan aktivitas pemain, 21 Sept 2026) ---
# Tabel manual app_db, tidak di reverse-sync — bisa dibangun ulang dari API.


def upsert_player_activity(rows: list[tuple]) -> int:
    """Upsert player_activity, return jumlah terkirim."""
    if not rows:
        return 0
    try:
        with local_session(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO player_activity (user_id, last_connection_at, checked_at)
                VALUES %s
                ON CONFLICT (user_id) DO UPDATE
                SET last_connection_at = EXCLUDED.last_connection_at,
                    checked_at = now()
                """,
                rows,
                template="(%s, %s::timestamptz, now())",
            )
            return len(rows)
    except Exception as exc:
        log.error(f"upsert_player_activity: gagal — {exc}")
        return 0


def get_owners_to_refresh(limit: int = 3000) -> list[str]:
    """Owner perlu dicek, urut prioritas."""
    try:
        with local_session() as cur:
            cur.execute(
                """
                SELECT o.owner_id
                FROM (SELECT DISTINCT owner_id FROM company_index
                      WHERE owner_id IS NOT NULL AND owner_id <> '') o
                LEFT JOIN player_activity p ON p.user_id = o.owner_id
                WHERE p.user_id IS NULL
                   OR (p.last_connection_at >= now() - interval '3 days'
                       AND p.checked_at < now() - interval '20 hours')
                   OR (p.last_connection_at >= now() - interval '30 days'
                       AND p.checked_at < now() - interval '3 days')
                   OR p.checked_at < now() - interval '7 days'
                ORDER BY (p.user_id IS NULL) DESC, p.checked_at ASC NULLS FIRST
                LIMIT %s
                """,
                (int(limit),),
            )
            return [r[0] for r in cur.fetchall()]
    except Exception as exc:
        log.error(f"get_owners_to_refresh: gagal — {exc}")
        return []


def get_player_activity_stats() -> dict:
    """Ringkasan buat memantau pengisian awal & cakupan."""
    empty = {"rows": 0, "active_3d": 0, "active_30d": 0, "checked_24h": 0, "no_date": 0,
             "owners_total": 0, "owners_covered": 0}

    try:
        with local_session() as cur:
            cur.execute(
                """
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE last_connection_at >= now() - interval '3 days'),
                       COUNT(*) FILTER (WHERE last_connection_at >= now() - interval '30 days'),
                       COUNT(*) FILTER (WHERE checked_at >= now() - interval '24 hours'),
                       COUNT(*) FILTER (WHERE last_connection_at IS NULL)
                FROM player_activity
                """
            )
            r = cur.fetchone()
            cur.execute(
                """
                SELECT COUNT(DISTINCT c.owner_id), COUNT(DISTINCT p.user_id)
                FROM company_index c LEFT JOIN player_activity p ON p.user_id = c.owner_id
                WHERE c.owner_id IS NOT NULL AND c.owner_id <> ''
                """
            )
            o = cur.fetchone()
        return {"rows": r[0], "active_3d": r[1], "active_30d": r[2], "checked_24h": r[3],
                "no_date": r[4], "owners_total": o[0], "owners_covered": o[1]}
    except Exception as exc:
        log.error(f"get_player_activity_stats: gagal — {exc}")
        return empty


def upsert_company_workers(company_id: str, workers: list[dict]) -> int:
    """Refresh worker+wage: delete lama, insert baru."""
    try:
        with local_session(commit=True) as cur:
            cur.execute(
                "DELETE FROM company_workers WHERE company_id = %s",
                (company_id,),
            )
            if workers:
                values = [
                    (
                        company_id,
                        w.get("userId") or w.get("user") or "",
                        float(w.get("wage") or 0),
                        w.get("joinedAt"),
                    )
                    for w in workers
                ]
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO company_workers
                    (company_id, worker_user_id, wage, joined_at, updated_at)
                    VALUES %s
                    """,
                    values,
                    template="(%s, %s, %s, %s, now())",
                )
            return len(workers)
    except Exception as exc:
        log.error(f"upsert_company_workers({company_id}): gagal — {exc}")
        return 0


def delete_company_workers_batch(company_ids: list[str]) -> int:
    """Hapus company_workers yang confirmed dibongkar."""
    if not company_ids:
        return 0
    try:
        with local_session(commit=True) as cur:
            cur.execute(
                "DELETE FROM company_workers WHERE company_id = ANY(%s)",
                (list(company_ids),),
            )
            return cur.rowcount
    except Exception as exc:
        log.error(f"delete_company_workers_batch: gagal ({len(company_ids)} id) — {exc}")
        return 0


def get_recently_logged_in_owners(lookback_minutes: int, limit: int = 500) -> list[str]:
    """Owner yang login dalam lookback_minutes terakhir."""
    try:
        with local_session() as cur:
            cur.execute(
                """
                SELECT DISTINCT p.user_id
                FROM player_activity p
                JOIN (
                    SELECT DISTINCT owner_id FROM company_index
                    WHERE owner_id IS NOT NULL AND owner_id <> ''
                ) o ON o.owner_id = p.user_id
                WHERE p.last_connection_at >= now() - (%s || ' minutes')::interval
                ORDER BY p.user_id
                LIMIT %s
                """,
                (lookback_minutes, limit),
            )
            return [r[0] for r in cur.fetchall()]
    except Exception as exc:
        log.error(f"get_recently_logged_in_owners: gagal — {exc}")
        return []


# --- company_scan_state (incremental cursor untuk fetch_all_companies_index) ---

def get_company_scan_state() -> dict:
    """Baca state cursor scan company (row 'global'). Return dict dengan
    last_cursor (str|None) dan cycle_count. Kalau row belum ada, kembalikan
    default {'last_cursor': None, 'cycle_count': 0}."""
    try:
        with local_session() as cur:
            cur.execute(
                "SELECT last_cursor, cycle_count FROM company_scan_state WHERE id = 'global'"
            )
            row = cur.fetchone()
            if not row:
                return {"last_cursor": None, "cycle_count": 0}
            return {"last_cursor": row[0], "cycle_count": int(row[1] or 0)}
    except Exception as exc:
        log.error(f"get_company_scan_state: gagal — {exc}")
        return {"last_cursor": None, "cycle_count": 0}


def set_company_scan_state(last_cursor: str | None, cycle_count: int) -> None:
    """Simpan state cursor scan company."""
    try:
        with local_session(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO company_scan_state (id, last_cursor, last_scanned_at, cycle_count)
                VALUES ('global', %s, now(), %s)
                ON CONFLICT (id) DO UPDATE
                SET last_cursor     = EXCLUDED.last_cursor,
                    last_scanned_at = EXCLUDED.last_scanned_at,
                    cycle_count     = EXCLUDED.cycle_count
                """,
                (last_cursor, cycle_count),
            )
    except Exception as exc:
        log.error(f"set_company_scan_state: gagal — {exc}")
