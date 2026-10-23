# market/rate_limit.py — rate limiter + global pause untuk WarEra API
from __future__ import annotations

import asyncio
import random as _bf_random
import time as _bf_time


class _RateLimiter:
    """Token-bucket: pacing request proaktif ke N/menit, bukan nembak
    kencang lalu mundur pas kena 429. Request tetep bisa jalan concurrent
    (asyncio.gather), throughput-nya aja yang dijaga mendekati limit asli."""

    def __init__(self, max_per_minute: int):
        self._interval = 60.0 / max_per_minute
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        loop = asyncio.get_event_loop()
        async with self._lock:
            now = loop.time()
            start = max(now, self._next_slot)
            self._next_slot = start + self._interval
            wait = start - now
        if wait > 0:
            await asyncio.sleep(wait)


_COMPANY_SCAN_RPM = 190
_paginate_limiter = _RateLimiter(_COMPANY_SCAN_RPM)
_detail1_limiter  = _RateLimiter(_COMPANY_SCAN_RPM)
_detail2_limiter  = _RateLimiter(_COMPANY_SCAN_RPM)

_TAX_FETCH_RPM = 90
_tax_limiter = _RateLimiter(_TAX_FETCH_RPM)


_BF_PAUSE_UNTIL: dict[str, float] = {}


def _bucket_key(headers: dict | None) -> str:
    """Kunci bucket rate-limit = nilai X-Api-Key; request tanpa key = bucket "_nokey"."""
    return (headers or {}).get("X-Api-Key") or "_nokey"


def _set_global_pause(seconds: float, key: str = "_nokey") -> None:
    _BF_PAUSE_UNTIL[key] = max(_BF_PAUSE_UNTIL.get(key, 0.0), _bf_time.monotonic() + seconds)


async def _respect_global_pause(key: str = "_nokey") -> None:
    now = _bf_time.monotonic()
    until = _BF_PAUSE_UNTIL.get(key, 0.0)
    if now < until:
        await asyncio.sleep(until - now + _bf_random.uniform(0.05, 0.5))


_activity_limiter = _RateLimiter(120)
