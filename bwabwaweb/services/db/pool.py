# db_pool.py

from __future__ import annotations

import logging

import psycopg2
import psycopg2.extras
from datetime import datetime as _dt, date as _date
from decimal import Decimal as _Decimal
import psycopg2.pool

from services.db.local import APP_DB_HOST, APP_DB_PORT, APP_DB_DBNAME, APP_DB_USER, APP_DB_PASSWORD

log = logging.getLogger("WarEraBot.db_pool")

DB_POOL_MIN_CONN = 1
DB_POOL_MAX_CONN = 6  # headroom app_db max=40 (baseline 14 + PostgREST 10 + territory 10).

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Lazy-init pool, singleton per proses, thread-safe."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            DB_POOL_MIN_CONN, DB_POOL_MAX_CONN,
            host=APP_DB_HOST, port=APP_DB_PORT, dbname=APP_DB_DBNAME,
            user=APP_DB_USER, password=APP_DB_PASSWORD,
            connect_timeout=10,
        )
        log.info(f"db_pool: connection pool dibuat (min={DB_POOL_MIN_CONN}, max={DB_POOL_MAX_CONN}).")
    return _pool


def _pool_get_conn():
    return _get_pool().getconn()


def _pool_put_conn(conn) -> None:
    """Kembalikan koneksi ke pool, bukan conn.close().

    JANGAN guard 'conn.closed == 0' — psycopg2 putconn handle closed conn
    (buka slot kembali). Guard itu bikin slot leak: kalau conn sudah closed,
    putconn tidak dipanggil, _used tetap terisi, lama-lama exhausted.
    Verified 29 Sep: test close() + putconn -> _used kembali 0.
    """
    if conn is None:
        return
    try:
        _get_pool().putconn(conn)
    except Exception as exc:
        log.error(f"_pool_put_conn: gagal kembalikan koneksi ke pool — {exc}")


def _shape_json_rows(rows: list[dict]) -> list[dict]:
    """Shape JSON PostgREST: date/datetime -> isoformat, Decimal -> float."""
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (_dt, _date)):
                r[k] = v.isoformat()
            elif isinstance(v, _Decimal):
                r[k] = float(v)
    return rows


def _adapt_value(v):
    """Paritas supabase-py: dict/list -> JSON wrapper eksplisit."""
    if isinstance(v, (dict, list)):
        return psycopg2.extras.Json(v)
    return v


class _QueryError(Exception):
    """Query gagal. Beda dari SDK Supabase — SDK return .error, ini raise."""


class Table:
    """Builder chainable mirip supabase.table(x). Akhiri dengan .execute()."""

    def __init__(self, name: str):
        self._name = name
        self._select_cols = "*"
        self._filters: list[tuple[str, str, object]] = []
        self._order_col: str | None = None
        self._order_desc = False
        self._limit: int | None = None
        self._op: str | None = None
        self._payload = None
        self._conflict_col: str | None = None

    def select(self, cols: str = "*") -> "Table":
        self._op = self._op or "select"
        self._select_cols = cols
        return self

    def eq(self, col: str, val) -> "Table":
        self._filters.append((col, "=", val))
        return self

    def gte(self, col: str, val) -> "Table":
        self._filters.append((col, ">=", val))
        return self

    def lte(self, col: str, val) -> "Table":
        self._filters.append((col, "<=", val))
        return self

    def lt(self, col: str, val) -> "Table":
        self._filters.append((col, "<", val))
        return self

    def in_(self, col: str, vals: list) -> "Table":
        self._filters.append((col, "IN", vals))
        return self

    def order(self, col: str, desc: bool = False) -> "Table":
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int) -> "Table":
        self._limit = n
        return self

    def insert(self, rows: dict | list[dict]) -> "Table":
        self._op = "insert"
        self._payload = rows if isinstance(rows, list) else [rows]
        return self

    def update(self, values: dict) -> "Table":
        self._op = "update"
        self._payload = values
        return self

    def upsert(self, rows: dict | list[dict], on_conflict: str,
               ignore_duplicates: bool = False) -> "Table":
        """ignore_duplicates=True -> ON CONFLICT DO NOTHING."""
        self._op = "upsert"
        self._payload = rows if isinstance(rows, list) else [rows]
        self._conflict_col = on_conflict
        self._ignore_duplicates = ignore_duplicates
        return self

    def delete(self) -> "Table":
        self._op = "delete"
        return self

    # --- build & execute ---

    def _where_clause(self) -> tuple[str, list]:
        if not self._filters:
            return "", []
        parts, params = [], []
        for col, op, val in self._filters:
            if op == "IN":
                parts.append(f"{col} = ANY(%s)")
                params.append(list(val))
            else:
                parts.append(f"{col} {op} %s")
                params.append(val)
        return " WHERE " + " AND ".join(parts), params

    def execute(self):
        if self._op is None or self._op == "select":
            return self._exec_select()
        if self._op == "insert":
            return self._exec_insert()
        if self._op == "update":
            return self._exec_update()
        if self._op == "upsert":
            return self._exec_upsert()
        if self._op == "delete":
            return self._exec_delete()
        raise _QueryError(f"operasi tidak dikenal: {self._op}")

    def _exec_select(self) -> list[dict]:
        where_sql, params = self._where_clause()
        sql = f"SELECT {self._select_cols} FROM {self._name}{where_sql}"
        if self._order_col:
            sql += f" ORDER BY {self._order_col} {'DESC' if self._order_desc else 'ASC'}"
        if self._limit is not None:
            sql += f" LIMIT {int(self._limit)}"
        conn = _pool_get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            log.error(f"Table({self._name}).select gagal — {exc}")
            raise _QueryError(str(exc)) from exc
        finally:
            _pool_put_conn(conn)
        # Output di-shape JSON PostgREST — tanpa ini caller fromisoformat() crash.
        for r in rows:
            for k, v in r.items():
                if isinstance(v, (_dt, _date)):
                    r[k] = v.isoformat()
                elif isinstance(v, _Decimal):
                    r[k] = float(v)
        return rows

    def _exec_insert(self):
        """Single-row -> RETURNING list[dict]. Multi-row -> bulk, return int."""
        if not self._payload:
            return 0
        cols = list(self._payload[0].keys())
        conn = _pool_get_conn()
        try:
            if len(self._payload) == 1:
                cols_sql = ", ".join(cols)
                vals_sql = ", ".join(["%s"] * len(cols))
                sql = f"INSERT INTO {self._name} ({cols_sql}) VALUES ({vals_sql}) RETURNING *"
                params = [_adapt_value(self._payload[0][c]) for c in cols]
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    rows = [dict(r) for r in cur.fetchall()]
                conn.commit()
                return _shape_json_rows(rows)
            sql = f"INSERT INTO {self._name} ({', '.join(cols)}) VALUES %s"
            values = [tuple(_adapt_value(row[c]) for c in cols) for row in self._payload]
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, sql, values)
            conn.commit()
            return len(self._payload)
        except Exception as exc:
            conn.rollback()
            log.error(f"Table({self._name}).insert gagal — {exc}")
            raise _QueryError(str(exc)) from exc
        finally:
            _pool_put_conn(conn)

    def _exec_update(self) -> int:
        where_sql, where_params = self._where_clause()
        set_cols = list(self._payload.keys())
        set_sql = ", ".join(f"{c} = %s" for c in set_cols)
        sql = f"UPDATE {self._name} SET {set_sql}{where_sql}"
        params = [self._payload[c] for c in set_cols] + where_params
        conn = _pool_get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                affected = cur.rowcount
            conn.commit()
            return affected
        except Exception as exc:
            conn.rollback()
            log.error(f"Table({self._name}).update gagal — {exc}")
            raise _QueryError(str(exc)) from exc
        finally:
            _pool_put_conn(conn)

    def _exec_upsert(self):
        """Single-row tanpa update_cols, atau ignore_duplicates -> DO NOTHING."""
        if not self._payload:
            return 0
        cols = list(self._payload[0].keys())
        update_cols = [c for c in cols if c not in self._conflict_col]
        do_update = bool(update_cols) and not getattr(self, "_ignore_duplicates", False)
        conn = _pool_get_conn()
        try:
            if len(self._payload) == 1:
                cols_sql = ", ".join(cols)
                vals_sql = ", ".join(["%s"] * len(cols))
                params = [_adapt_value(self._payload[0][c]) for c in cols]
                if do_update:
                    set_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
                    sql = f"INSERT INTO {self._name} ({cols_sql}) VALUES ({vals_sql}) ON CONFLICT ({self._conflict_col}) DO UPDATE SET {set_sql}"
                else:
                    sql = f"INSERT INTO {self._name} ({cols_sql}) VALUES ({vals_sql}) ON CONFLICT ({self._conflict_col}) DO NOTHING"
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    affected = cur.rowcount
                conn.commit()
                return affected
            values = [tuple(_adapt_value(row[c]) for c in cols) for row in self._payload]
            if do_update:
                set_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
                sql = f"INSERT INTO {self._name} ({', '.join(cols)}) VALUES %s ON CONFLICT ({self._conflict_col}) DO UPDATE SET {set_sql}"
            else:
                sql = f"INSERT INTO {self._name} ({', '.join(cols)}) VALUES %s ON CONFLICT ({self._conflict_col}) DO NOTHING"
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, sql, values)
                affected = cur.rowcount
            conn.commit()
            return affected
        except Exception as exc:
            conn.rollback()
            log.error(f"Table({self._name}).upsert gagal — {exc}")
            raise _QueryError(str(exc)) from exc
        finally:
            _pool_put_conn(conn)

    def _exec_delete(self) -> int:
        where_sql, params = self._where_clause()
        if not where_sql:
            raise _QueryError("delete() tanpa filter (.eq/.in_) ditolak — cegah DELETE tanpa WHERE")
        sql = f"DELETE FROM {self._name}{where_sql}"
        conn = _pool_get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                affected = cur.rowcount
            conn.commit()
            return affected
        except Exception as exc:
            conn.rollback()
            log.error(f"Table({self._name}).delete gagal — {exc}")
            raise _QueryError(str(exc)) from exc
        finally:
            _pool_put_conn(conn)


def table(name: str) -> Table:
    return Table(name)


class _RpcCall:
    """Chainable rpc("fn", params).execute(). Named notation biar urutan aman."""

    def __init__(self, fn_name: str, params: dict):
        self._fn = fn_name
        self._params = params or {}

    def execute(self) -> list[dict]:
        bad = [k for k in self._params if not k.isidentifier()]
        if bad:
            raise _QueryError(f"rpc({self._fn}): nama argumen tidak valid: {bad}")
        if self._params:
            assigns = ", ".join(f"{k} => %s" for k in self._params)
            sql = f"SELECT * FROM {self._fn}({assigns})"
            values = list(self._params.values())
        else:
            sql = f"SELECT * FROM {self._fn}()"
            values = []
        conn = _pool_get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, values)
                rows = [dict(r) for r in cur.fetchall()]
            conn.commit()
            return _shape_json_rows(rows)
        except Exception as exc:
            conn.rollback()
            log.error(f"rpc({self._fn}) gagal — {exc}")
            raise _QueryError(str(exc)) from exc
        finally:
            _pool_put_conn(conn)


def rpc(fn_name: str, params: dict) -> _RpcCall:
    return _RpcCall(fn_name, params)
