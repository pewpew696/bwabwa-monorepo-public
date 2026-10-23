# local_db.py — koneksi psycopg2 ke PostgreSQL lokal (app_db)
# dipake spy_cache_store.py & territory_tax_store.py, gantiin yugabyte
# gak pake SSL krna akses via localhost doang, gak lewat internet

from __future__ import annotations

import os

import psycopg2
from contextlib import contextmanager

APP_DB_HOST     = os.environ.get("APP_DB_HOST", "127.0.0.1")
APP_DB_PORT     = os.environ.get("APP_DB_PORT", "5432")
APP_DB_DBNAME   = os.environ.get("APP_DB_DBNAME", "app_db")
APP_DB_USER     = os.environ.get("APP_DB_USER", "")
APP_DB_PASSWORD = os.environ.get("APP_DB_PASSWORD", "")


def _local_connect():
    return psycopg2.connect(
        host=APP_DB_HOST,
        port=APP_DB_PORT,
        dbname=APP_DB_DBNAME,
        user=APP_DB_USER,
        password=APP_DB_PASSWORD,
        connect_timeout=10,
    )


@contextmanager
def local_session(commit: bool = False):
    """Context manager koneksi local (bukan pool, koneksi baru tiap call).
    Get conn -> yield cursor -> commit (opsional) -> close (selalu).
    Caller WAJIB wrap try/except (connect bisa raise).
    """
    conn = _local_connect()
    try:
        with conn.cursor() as cur:
            yield cur
            if commit:
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def local_session_raw():
    """Context manager koneksi local — yield conn mentah, caller urus
    commit/rollback/cursor sendiri. Buat loop chunk yang butuh commit
    per-chunk (mis. upsert_companies_batch)."""
    conn = _local_connect()
    try:
        yield conn
    finally:
        conn.close()
