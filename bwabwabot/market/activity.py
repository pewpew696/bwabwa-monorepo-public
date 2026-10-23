# market/activity.py — round, government, workers, player activity
from __future__ import annotations

import asyncio
import logging

import aiohttp

from .auth import _auth_headers, _hub_auth_headers
from .client import _encode, _get_json_with_retry
from .constants import BASE_URL, GOVERNMENT_URL, ROUND_URL, WORKERS_URL
from .rate_limit import _activity_limiter, _bf_time

log = logging.getLogger("WarEraBot.market")


async def fetch_round(session: aiohttp.ClientSession, round_id: str) -> dict | None:
    """Data live 1 round battle (attacker.points, defender.points, dst)."""
    try:
        url = f"{ROUND_URL}?input={_encode({'roundId': round_id})}"
        resp = await _get_json_with_retry(session, url, headers=_auth_headers(), timeout=10)
        return resp["result"]["data"]
    except Exception as exc:
        log.error(f"fetch_round({round_id}): {exc}")
        return None


async def fetch_government(session: aiohttp.ClientSession, country_id: str) -> dict | None:
    """Data pemerintahan (president, vp, congress, dst) 1 negara."""
    try:
        url = f"{GOVERNMENT_URL}?input={_encode({'countryId': country_id})}"
        resp = await _get_json_with_retry(session, url, headers=_auth_headers(), timeout=10)
        return resp["result"]["data"]
    except Exception as exc:
        log.error(f"fetch_government({country_id}): {exc}")
        return None


_WORKERS_TTL_SECONDS = 90
_workers_cache = {}
_workers_inflight = {}


async def fetch_workers(session: aiohttp.ClientSession, company_id: str) -> list[dict] | None:
    """Singleflight + TTL: beberapa modul minta company_id yang sama
    bersamaan → cuma 1 request keluar, sisanya nunggu hasil yang sama.

    Return None = fetch GAGAL (error HTTP/parse) — TIDAK di-cache, supaya
    kegagalan transient nggak bikin pabrik tampak kosong 90 detik.
    Return list (bisa kosong) = sukses."""
    if _WORKERS_TTL_SECONDS > 0:
        cached = _workers_cache.get(company_id)
        if cached is not None and (_bf_time.monotonic() - cached[0]) < _WORKERS_TTL_SECONDS:
            return cached[1]

    existing = _workers_inflight.get(company_id)
    if existing is not None:
        return await asyncio.shield(existing)

    task = asyncio.ensure_future(_fetch_workers_once(session, company_id))
    _workers_inflight[company_id] = task
    try:
        result = await task
        if result is not None and _WORKERS_TTL_SECONDS > 0:
            if len(_workers_cache) > 5000:
                _workers_cache.clear()
            _workers_cache[company_id] = (_bf_time.monotonic(), result)
        return result
    finally:
        _workers_inflight.pop(company_id, None)


async def _fetch_workers_once(session: aiohttp.ClientSession, company_id: str) -> list[dict] | None:
    """List worker (+wage) buat 1 company. Dipanggil live, bukan di
    background scan. Return None saat gagal (jangan [] — None = error,
    [] = memang kosong)."""
    try:
        url = f"{WORKERS_URL}?input={_encode({'companyId': company_id})}"
        resp = await _get_json_with_retry(session, url, headers=_auth_headers(), timeout=10)
        data = resp["result"]["data"]
        # guard shape: data bukan dict (respons berubah/list) → jangan
        # dibiarkan jadi AttributeError yang ditelan jadi "kosong".
        if not isinstance(data, dict):
            log.warning(f"fetch_workers({company_id}): shape respons tak terduga ({type(data).__name__})")
            return None
        return data.get("workers") or []
    except Exception as exc:
        log.error(f"fetch_workers({company_id}): {type(exc).__name__}: {exc!r}")
        return None


PLAYER_BATCH_SIZE = 50


async def _fetch_player_lite_batch(
    session: aiohttp.ClientSession, ids: list[str]
) -> dict[str, str | None]:
    """Return {user_id: lastConnectionAt (ISO) | None}. None = akun tidak ditemukan / tanpa tanggal.
    ID yang gagal karena error sementara (429 habis retry, jaringan, 5xx) TIDAK dimasukkan ke
    hasil: tidak disimpan, dicoba lagi di putaran berikutnya. Batch HTTP 404 (semua ID tidak ada)
    dibelah dua sampai ID tunggal (=None). Batch campuran (HTTP 207) dibaca per elemen."""
    methods = ",".join(["user.getUserLite"] * len(ids))
    inputs = {str(i): {"userId": uid} for i, uid in enumerate(ids)}
    url = f"{BASE_URL}/{methods}?batch=1&input={_encode(inputs)}"
    try:
        results = await _get_json_with_retry(
            session, url, headers=_hub_auth_headers(), timeout=40, rate_limiter=_activity_limiter
        )
    except aiohttp.ClientResponseError as exc:
        if exc.status == 404:
            if len(ids) == 1:
                return {ids[0]: None}
            mid = len(ids) // 2
            left = await _fetch_player_lite_batch(session, ids[:mid])
            right = await _fetch_player_lite_batch(session, ids[mid:])
            return {**left, **right}
        log.warning(f"fetch_player_last_connections: HTTP {exc.status} ({len(ids)} ID) — dicoba lagi nanti")
        return {}
    except Exception as exc:
        log.warning(f"fetch_player_last_connections: {type(exc).__name__}: {exc!r} ({len(ids)} ID) — dicoba lagi nanti")
        return {}
    if not isinstance(results, list):
        return {}
    out: dict[str, str | None] = {}
    for i, uid in enumerate(ids):
        res = results[i] if i < len(results) else None
        if not isinstance(res, dict):
            continue
        data = (res.get("result") or {}).get("data")
        if data:
            out[uid] = ((data.get("dates") or {}).get("lastConnectionAt")) or None
        elif "error" in res:
            out[uid] = None
    return out


async def fetch_player_last_connections(
    session: aiohttp.ClientSession, user_ids: list[str]
) -> dict[str, str | None]:
    """{user_id: lastConnectionAt | None} untuk user_ids, batch 50 berurutan lewat token HUB."""
    out: dict[str, str | None] = {}
    for i in range(0, len(user_ids), PLAYER_BATCH_SIZE):
        out.update(await _fetch_player_lite_batch(session, user_ids[i:i + PLAYER_BATCH_SIZE]))
    return out
