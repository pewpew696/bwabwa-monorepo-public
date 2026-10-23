# market/usernames.py — resolve user_id -> username (cache + API)
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from services.db import pool as db_pool

from .auth import _auth_headers, _donation_auth_headers
from .client import _encode
from .constants import USER_LITE_URL

log = logging.getLogger("WarEraBot.market")


USERNAME_MAX_RETRIES   = 2


async def _fetch_username_with_retry(
    session: aiohttp.ClientSession, user_id: str, headers: dict, log_prefix: str
) -> str:
    """Fetch 1 username via user.getUserLite. Retry manual (fixed count +
    delay 1 detik, bukan backoff eksponensial) sengaja — ini dipanggil
    banyak sekaligus/paralel, retry lambat-tapi-pasti lebih ramah daripada
    semua request nunggu backoff panjang barengan.

    Selalu return string (fallback user_id[:8]+"..."), gak pernah raise —
    caller expect ini."""
    url = f"{USER_LITE_URL}?input={_encode({'userId': user_id})}"
    for attempt in range(USERNAME_MAX_RETRIES):
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = (await r.json(content_type=None))["result"]["data"]
                    return data.get("username") or user_id[:8] + "..."
                log.warning(f"{log_prefix}({user_id}): HTTP {r.status} (attempt {attempt + 1})")
        except Exception as exc:
            log.warning(f"{log_prefix}({user_id}): attempt {attempt + 1}/{USERNAME_MAX_RETRIES} gagal: {exc}")
        if attempt + 1 < USERNAME_MAX_RETRIES:
            await asyncio.sleep(1)
    return user_id[:8] + "..."


async def fetch_username(
    session: aiohttp.ClientSession, user_id: str, cache: dict, headers: Optional[dict] = None
) -> str:
    if user_id in cache:
        return cache[user_id]
    name = await _fetch_username_with_retry(session, user_id, headers or _auth_headers(), "fetch_username")
    cache[user_id] = name
    return name


_USERNAME_CACHE_TABLE = "username_cache"

_USERNAME_RESET_HOUR_UTC = 0


def _last_username_reset(now: datetime) -> datetime:
    """Titik reset harian terakhir (<= now), dalam UTC."""
    return now.replace(hour=_USERNAME_RESET_HOUR_UTC, minute=0, second=0, microsecond=0)


USERNAME_FETCH_CONCURRENCY = 4


async def resolve_usernames_bulk(
    session: aiohttp.ClientSession,
    buyer_ids: list[str],
    headers: Optional[dict] = None,
) -> dict[str, str]:
    """Resolve banyak buyer_id -> username sekaligus. Prioritas cache, valid
    sampai reset harian jam 07:00 WIB (00:00 UTC), bukan rolling TTL — lihat
    _last_username_reset(). Sisanya fetch API, dibatasi
    USERNAME_FETCH_CONCURRENCY paralel biar buyer baru yang belum ke-cache
    gak nembak API bareng dan kena 429 (kejadian nyata di log)."""
    unique_ids = list({b for b in buyer_ids if b})
    if not unique_ids:
        return {}

    result: dict[str, str] = {}
    stale_or_missing: list[str] = []
    now = datetime.now(timezone.utc)

    try:
        res = await asyncio.to_thread(
            lambda: (
                db_pool.table(_USERNAME_CACHE_TABLE)
                .select("*")
                .in_("user_id", unique_ids)
                .execute()
            )
        )
        cached_rows = res or []
    except Exception as exc:
        log.error(f"resolve_usernames_bulk: gagal baca username_cache ({exc})")
        cached_rows = []

    reset_point = _last_username_reset(now)
    cached_map = {row["user_id"]: row for row in cached_rows}
    for uid in unique_ids:
        row = cached_map.get(uid)
        if row:
            try:
                cached_at = datetime.fromisoformat(str(row["cached_at"]).replace("Z", "+00:00"))
            except Exception:
                cached_at = None
            if cached_at and cached_at >= reset_point:
                result[uid] = row["username"]
                continue
        stale_or_missing.append(uid)

    if not stale_or_missing:
        return result

    req_headers = headers or _donation_auth_headers()
    sem = asyncio.Semaphore(USERNAME_FETCH_CONCURRENCY)

    async def _fetch_one(uid: str) -> tuple[str, str]:
        async with sem:
            name = await _fetch_username_with_retry(session, uid, req_headers, "resolve_usernames_bulk")
            return uid, name

    fetched = await asyncio.gather(*[_fetch_one(uid) for uid in stale_or_missing])

    upsert_rows = []
    for uid, name in fetched:
        result[uid] = name
        if name == uid[:8] + "...":
            continue
        upsert_rows.append({"user_id": uid, "username": name, "cached_at": now.isoformat()})

    if upsert_rows:
        try:
            await asyncio.to_thread(
                lambda: db_pool.table(_USERNAME_CACHE_TABLE).upsert(upsert_rows, on_conflict="user_id").execute()
            )
        except Exception as exc:
            log.error(f"resolve_usernames_bulk: gagal simpan username_cache ({exc})")

    return result
