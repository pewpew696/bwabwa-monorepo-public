# market/client.py — HTTP client + retry untuk WarEra API
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from typing import Optional

import aiohttp

from .rate_limit import (
    _RateLimiter,
    _bucket_key,
    _respect_global_pause,
    _set_global_pause,
)

log = logging.getLogger("WarEraBot.market")


def _encode(params: dict) -> str:
    return urllib.parse.quote(json.dumps(params, separators=(",", ":")))


async def _get_json_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict,
    timeout: int = 15,
    max_retries: int = 3,
    rate_limiter: "Optional[_RateLimiter]" = None,
) -> dict:
    """GET + parse JSON dengan retry backoff buat 429 (cek Retry-After dulu)
    dan error jaringan (timeout/connection error — ini beneran kejadian pas
    testing paginasi donasi, bukan cuma teori). Status non-429 tetap langsung
    raise biar error lain gak ketutupan retry yang gak perlu.

    rate_limiter opsional: kalau diisi, request dipacing proaktif (token-
    bucket) alih-alih nembak kencang lalu mundur pas kena 429. Dipake khusus
    company-scan; caller lain tanpa ini gak berubah perilakunya."""
    delay = 2
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            if rate_limiter is not None:
                await rate_limiter.acquire()
            await _respect_global_pause(_bucket_key(headers))
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as r:
                if r.status == 429:
                    last_exc = aiohttp.ClientResponseError(
                        r.request_info, r.history, status=429, message="Too Many Requests"
                    )
                    if attempt < max_retries - 1:
                        retry_after = r.headers.get("Retry-After")
                        wait = float(retry_after) if retry_after else delay
                        _set_global_pause(wait + 0.5, _bucket_key(headers))
                        log.warning(
                            f"429 dari {url} — retry #{attempt + 1}/{max_retries - 1} "
                            f"dalam {wait}s" + (" (dari header Retry-After)" if retry_after else "")
                        )
                        await asyncio.sleep(wait)
                        delay *= 2
                        continue
                    raise last_exc
                r.raise_for_status()
                return await r.json(content_type=None)
        except aiohttp.ClientResponseError as exc:
            if exc.status != 429:
                raise
            last_exc = exc
            if attempt >= max_retries - 1:
                raise
            await asyncio.sleep(delay)
            delay *= 2
        except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as exc:
            last_exc = exc
            if attempt >= max_retries - 1:
                raise
            log.warning(
                f"Error jaringan dari {url} ({exc!r}) — retry #{attempt + 1}/"
                f"{max_retries - 1} dalam {delay}s"
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise last_exc or RuntimeError(f"_get_json_with_retry gagal tanpa exception jelas: {url}")
