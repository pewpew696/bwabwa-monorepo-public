# market/companies_helpers.py — helper pipeline company scan
from __future__ import annotations

import asyncio
import logging

import aiohttp

from .client import _encode, _get_json_with_retry
from .constants import BASE_URL
from .rate_limit import _RateLimiter

log = logging.getLogger("WarEraBot.market")


COMPANY_BATCH_SIZE     = 30


_DETAIL_WORKER_CONCURRENCY = 15


def _company_row_from_detail(cid: str, d: dict) -> dict:
    active_upgrades = d.get("activeUpgradeLevels") or {}
    return {
        "company_id":      cid,
        "region_id":       d.get("region", ""),
        "item_code":       d.get("itemCode", ""),
        "worker_count":    int(d.get("workerCount") or 0),
        "owner_id":        d.get("user", ""),
        "name":            d.get("name", ""),
        "production_rate": float(d.get("production") or 0),
        "estimated_value": float(d.get("estimatedValue") or 0),
        "ae_level":        int(active_upgrades.get("automatedEngine") or 0),
        "is_full":         bool(d.get("isFull") or False),
    }


async def _fetch_one_chunk_detail(
    session: aiohttp.ClientSession,
    chunk: list[str],
    headers: dict,
    limiter: _RateLimiter,
    label: str,
) -> tuple[dict[str, dict], bool]:
    """Fetch detail buat 1 chunk (<=COMPANY_BATCH_SIZE id). Return (hasil, sukses?)."""
    try:
        methods = ",".join(["company.getById"] * len(chunk))
        inputs  = {str(i): {"companyId": cid} for i, cid in enumerate(chunk)}
        url     = f"{BASE_URL}/{methods}?batch=1&input={_encode(inputs)}"
        results = await _get_json_with_retry(
            session, url, headers=headers, timeout=30, rate_limiter=limiter
        )
        if not isinstance(results, list):
            return {}, False
        out: dict[str, dict] = {}
        for i, result in enumerate(results):
            if i >= len(chunk):
                break
            cid  = chunk[i]
            data = result.get("result", {}).get("data")
            if data:
                out[cid] = data
        return out, True
    except Exception as exc:
        log.warning(f"_fetch_one_chunk_detail[{label}]: chunk gagal ({exc!r})")
        return {}, False


async def _run_detail_chunks(
    session: aiohttp.ClientSession,
    chunks: list[list[str]],
    headers: dict,
    limiter: _RateLimiter,
    label: str,
) -> tuple[dict[str, dict], list[list[str]]]:
    """Jalankan semua chunk concurrent (dibatasi semaphore, dipacing
    rate_limiter proaktif), bukan satu-satu berurutan — ini yang bikin
    throughput riil mendekati kuota per-menit token. Return (hasil gabungan,
    chunk yang gagal buat di-retry belakangan)."""
    sem = asyncio.Semaphore(_DETAIL_WORKER_CONCURRENCY)
    failed: list[list[str]] = []
    out: dict[str, dict] = {}

    async def _bound(chunk: list[str]):
        async with sem:
            data, ok = await _fetch_one_chunk_detail(session, chunk, headers, limiter, label)
            return chunk, data, ok

    for chunk, data, ok in await asyncio.gather(*[_bound(c) for c in chunks]):
        if ok:
            out.update(data)
        else:
            failed.append(chunk)
    return out, failed
