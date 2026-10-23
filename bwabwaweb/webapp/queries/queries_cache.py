"""Baca/tulis tabel web_cache (terpisah dari api_cache milik bot)."""
import json
from datetime import datetime, timezone

from webapp.core.database import fetch_dicts, web_session


def get_cache(cache_key: str) -> dict | None:
    """Return {'data': ..., 'fetched_at': datetime} atau None."""
    with web_session() as cursor:
        cursor.execute(
            "SELECT data, fetched_at FROM web_cache WHERE cache_key = %s",
            (cache_key,),
        )
        rows = fetch_dicts(cursor)
    if not rows:
        return None
    return {"data": rows[0]["data"], "fetched_at": rows[0]["fetched_at"]}


def set_cache(cache_key: str, data: dict) -> None:
    with web_session(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO web_cache (cache_key, data, fetched_at)
            VALUES (%s, %s, now())
            ON CONFLICT (cache_key)
            DO UPDATE SET data = EXCLUDED.data, fetched_at = now()
            """,
            (cache_key, json.dumps(data)),
        )


def is_fresh(fetched_at: datetime | None, ttl_seconds: int) -> bool:
    if fetched_at is None:
        return False
    age = datetime.now(timezone.utc) - fetched_at
    return age.total_seconds() < ttl_seconds
