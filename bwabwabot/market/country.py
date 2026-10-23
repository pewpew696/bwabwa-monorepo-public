# market/country.py — data negara, cache negara/bonus, tax breakdown
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from services.db import pool as db_pool

from .auth import HEADERS, _auth_headers
from .bonus import _country_bonus_pct, _deposit_bonus_pct
from .client import _encode, _get_json_with_retry
from .constants import (
    BASE_URL,
    COUNTRIES_URL,
    COUNTRY_BY_ID_URL,
    ITEM_LABELS,
    REGIONS_URL,
)
from .items import _label
from .rate_limit import _RateLimiter, _tax_limiter

log = logging.getLogger("WarEraBot.market")


PARTY_BATCH_SIZE = 50


async def _fetch_parties_batch(session: aiohttp.ClientSession, party_ids: list[str]) -> dict[str, dict]:
    if not party_ids:
        return {}
    parties_by_id: dict[str, dict] = {}
    unique_ids = list(set(party_ids))
    chunks = [unique_ids[i:i + PARTY_BATCH_SIZE] for i in range(0, len(unique_ids), PARTY_BATCH_SIZE)]

    for chunk in chunks:
        try:
            methods = ",".join(["party.getById"] * len(chunk))
            inputs  = {str(i): {"partyId": pid} for i, pid in enumerate(chunk)}
            url     = f"{BASE_URL}/{methods}?batch=1&input={_encode(inputs)}"
            results = await _get_json_with_retry(session, url, headers=HEADERS, timeout=30)
            if not isinstance(results, list):
                continue
            for i, result in enumerate(results):
                if i >= len(chunk):
                    break
                pid  = chunk[i]
                data = result.get("result", {}).get("data")
                if data:
                    parties_by_id[pid] = data
        except Exception as exc:
            log.warning(f"Party batch fetch error: {exc}")
            continue

    log.info(f"Party batch: {len(parties_by_id)}/{len(unique_ids)} loaded.")
    return parties_by_id


_CACHE_TTL_COUNTRIES = 30 * 24 * 3600
_CACHE_TTL_BONUS     = 2 * 3600
_CACHE_TTL_REGIONS   = 24 * 3600
_CACHE_TTL_GOVERNMENT = 24 * 3600
_CACHE_TABLE         = "api_cache"

_country_cache_mem: dict | None = None
_bonus_raw_cache_mem: dict | None = None
_regions_cache_mem: dict | None = None


async def _load_cache_row(with_cache: bool, cache_key: str, ttl_seconds: int):
    """Baca 1 baris cache dari api_cache. None kalau gak ada/expired/with_cache False
    gak tersedia."""
    if not with_cache:
        return None
    try:
        res = await asyncio.to_thread(
            lambda: (
                db_pool.table(_CACHE_TABLE)
                .select("data, fetched_at")
                .eq("cache_key", cache_key)
                .execute()
            )
        )
        rows = res or []
        if not rows:
            return None
        fetched_at_raw = rows[0]["fetched_at"]
        fetched_at = datetime.fromisoformat(fetched_at_raw.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age > ttl_seconds:
            return None
        return rows[0]["data"]
    except Exception as exc:
        log.warning(f"_load_cache_row({cache_key}): {exc}")
        return None


async def _save_cache_row(with_cache: bool, cache_key: str, data) -> None:
    """Simpan/update 1 baris cache. Gagal simpan bukan fatal — cache
    in-memory tetep kepakai buat sisa umur proses ini."""
    if not with_cache:
        return
    try:
        await asyncio.to_thread(
            lambda: db_pool.table(_CACHE_TABLE).upsert(
                {
                    "cache_key": cache_key,
                    "data": data,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="cache_key",
            ).execute()
        )
    except Exception as exc:
        log.warning(f"_save_cache_row({cache_key}): {exc}")


async def get_country_list(
    session: aiohttp.ClientSession,
    with_cache: bool = False,
    headers: Optional[dict] = None,
    force_refresh: bool = False,
) -> list[dict]:
    """Sumber tunggal buat getAllCountries, dipake bareng fetch_country_id_by_name,
    fetch_max_bonuses, fetch_bonus_breakdown — biar 1x fetch dipakai bersama.

    Urutan cek: in-memory -> Supabase -> fetch API baru."""
    global _country_cache_mem
    now = datetime.now(timezone.utc)
    req_headers = headers or _auth_headers()

    if not force_refresh and _country_cache_mem is not None:
        age = (now - _country_cache_mem["fetched_at"]).total_seconds()
        if age < _CACHE_TTL_COUNTRIES:
            return _country_cache_mem["data"]

    if not force_refresh:
        db_data = await _load_cache_row(with_cache, "countries", _CACHE_TTL_COUNTRIES)
        if db_data is not None:
            _country_cache_mem = {"data": db_data, "fetched_at": now}
            return db_data

    try:
        result = await _get_json_with_retry(session, COUNTRIES_URL, req_headers)
        countries: list = result.get("result", {}).get("data") or []
    except Exception as exc:
        log.error(f"get_country_list fetch gagal: {exc}")
        if _country_cache_mem is not None:
            return _country_cache_mem["data"]
        return []

    _country_cache_mem = {"data": countries, "fetched_at": now}
    await _save_cache_row(with_cache, "countries", countries)
    return countries


async def get_regions_object(
    session: aiohttp.ClientSession,
    with_cache: bool = False,
    headers: Optional[dict] = None,
    force_refresh: bool = False,
) -> dict:
    """Sumber tunggal region.getRegionsObject (dict region_id -> region).
    TTL 24 jam. Urutan cek: in-memory -> Supabase -> fetch API baru.

    Sebelumnya 7 tempat fetch REGIONS_URL sendiri-sendiri (country_routes,
    search_routes, spy/*, alert/base) -- helper ini buat shared cache.
    Caller lama belum semua migrasi; migrasi bertahap.
    """
    global _regions_cache_mem
    now = datetime.now(timezone.utc)
    req_headers = headers or _auth_headers()

    if not force_refresh and _regions_cache_mem is not None:
        age = (now - _regions_cache_mem["fetched_at"]).total_seconds()
        if age < _CACHE_TTL_REGIONS:
            return _regions_cache_mem["data"]

    if not force_refresh:
        db_data = await _load_cache_row(with_cache, "regions_obj", _CACHE_TTL_REGIONS)
        if db_data is not None:
            _regions_cache_mem = {"data": db_data, "fetched_at": now}
            return db_data

    try:
        result = await _get_json_with_retry(session, REGIONS_URL, req_headers, timeout=30)
        regions_obj: dict = result.get("result", {}).get("data") or {}
    except Exception as exc:
        log.error(f"get_regions_object fetch gagal: {exc}")
        if _regions_cache_mem is not None:
            return _regions_cache_mem["data"]
        return {}

    _regions_cache_mem = {"data": regions_obj, "fetched_at": now}
    await _save_cache_row(with_cache, "regions_obj", regions_obj)
    return regions_obj


async def get_government_cached(
    session: aiohttp.ClientSession,
    country_id: str,
    with_cache: bool = False,
) -> dict | None:
    """Cache government (president/VP/menteri/congress) TTL 24 jam.
    DB-only (api_cache table) -- tidak pakai mem-cache karena variasi
    country_id tinggi, hit rate mem rendah.

    Fallback ke fetch_government kalau cache miss / with_cache False.
    """
    from .activity import fetch_government
    cache_key = f"gov:{country_id}"

    if with_cache:
        db_data = await _load_cache_row(with_cache, cache_key, _CACHE_TTL_GOVERNMENT)
        if db_data is not None:
            return db_data

    gov = await fetch_government(session, country_id)
    if gov is not None and with_cache:
        await _save_cache_row(with_cache, cache_key, gov)
    return gov


async def get_bonus_raw_data(
    session: aiohttp.ClientSession,
    with_cache: bool = False,
    headers: Optional[dict] = None,
    force_refresh: bool = False,
) -> tuple[list[dict], dict]:
    """Sumber tunggal (countries, regions_obj) buat fetch_max_bonuses &
    fetch_bonus_breakdown. TTL 3 jam, lebih pendek dari get_country_list
    krna rulingParty/specializedItem bisa berubah lebih cepat."""
    global _bonus_raw_cache_mem
    now = datetime.now(timezone.utc)
    req_headers = headers or _auth_headers()

    if not force_refresh and _bonus_raw_cache_mem is not None:
        age = (now - _bonus_raw_cache_mem["fetched_at"]).total_seconds()
        if age < _CACHE_TTL_BONUS:
            return _bonus_raw_cache_mem["data"]["countries"], _bonus_raw_cache_mem["data"]["regions_obj"]

    if not force_refresh:
        db_data = await _load_cache_row(with_cache, "bonus_raw", _CACHE_TTL_BONUS)
        if db_data is not None:
            _bonus_raw_cache_mem = {"data": db_data, "fetched_at": now}
            return db_data["countries"], db_data["regions_obj"]

    try:
        result = await _get_json_with_retry(session, COUNTRIES_URL, req_headers)
        countries: list = result.get("result", {}).get("data") or []
    except Exception as exc:
        log.error(f"get_bonus_raw_data countries fetch gagal: {exc}")
        if _bonus_raw_cache_mem is not None:
            return _bonus_raw_cache_mem["data"]["countries"], _bonus_raw_cache_mem["data"]["regions_obj"]
        countries = []

    regions_obj: dict = {}
    try:
        result = await _get_json_with_retry(session, REGIONS_URL, req_headers, timeout=20)
        regions_obj = result.get("result", {}).get("data") or {}
    except Exception as exc:
        log.warning(f"get_bonus_raw_data regions fetch gagal: {exc}")

    payload = {"countries": countries, "regions_obj": regions_obj}
    _bonus_raw_cache_mem = {"data": payload, "fetched_at": now}
    await _save_cache_row(with_cache, "bonus_raw", payload)
    return countries, regions_obj


async def fetch_max_bonuses(
    session: aiohttp.ClientSession,
    with_cache: bool = False,
    raw_data: Optional[tuple[list[dict], dict]] = None,
    parties_by_id: Optional[dict[str, dict]] = None,
) -> dict[str, float]:
    """raw_data & parties_by_id opsional — reuse dari caller (lihat
    fetch_median_bonuses) biar gak fetch dobel dalam 1 siklus refresh."""
    try:
        countries, regions_obj = raw_data if raw_data is not None else await get_bonus_raw_data(session, with_cache=with_cache)
        countries_by_id = {c["_id"]: c for c in countries if c.get("_id")}
        if parties_by_id is None:
            party_ids = list({c.get("rulingParty") for c in countries_by_id.values() if c.get("rulingParty")})
            parties_by_id = await _fetch_parties_batch(session, party_ids)

        now = datetime.now(timezone.utc)
        max_bonus: dict[str, float] = {}
        if regions_obj:
            for region in regions_obj.values():
                if not region:
                    continue
                country_id = region.get("country")
                country    = countries_by_id.get(country_id) if country_id else None
                party      = parties_by_id.get(country.get("rulingParty")) if country else None
                for item_id in ITEM_LABELS:
                    total = _country_bonus_pct(country, item_id, party) + _deposit_bonus_pct(region, item_id, party, now)
                    if total > max_bonus.get(item_id, 0):
                        max_bonus[item_id] = total
        else:
            for country in countries_by_id.values():
                party = parties_by_id.get(country.get("rulingParty"))
                for item_id in ITEM_LABELS:
                    total = _country_bonus_pct(country, item_id, party)
                    if total > max_bonus.get(item_id, 0):
                        max_bonus[item_id] = total

        return {_label(item_id): round(pct, 2) for item_id, pct in max_bonus.items() if pct > 0}
    except Exception as exc:
        log.error(f"fetch_max_bonuses: {exc}")
        return {}


async def fetch_median_bonuses(
    session: aiohttp.ClientSession,
    with_cache: bool = False,
    raw_data: Optional[tuple[list[dict], dict]] = None,
    parties_by_id: Optional[dict[str, dict]] = None,
) -> dict[str, float]:
    """Median bonus produksi per item dari Populasi B (negara/region dengan
    total>0), bukan max kayak fetch_max_bonuses. fetch_max_bonuses pake bonus
    tertinggi lintas negara (cuma dimiliki segelintir negara elite), bikin
    production_cost jauh di bawah harga pasar riil.

    Iterasi sengaja di-mirror persis fetch_max_bonuses biar distribusinya
    identik dengan yang udah divalidasi (726 negara/region x 20 item).
    Bedanya cuma simpan semua total, bukan cuma max, lalu ambil median dari
    yang total>0.

    Item dengan Populasi B kosong tetep masuk dict dengan nilai 0.0 eksplisit
    (beda dari key hilang, yang berarti fetch gagal total) — biar caller bisa
    bedain "median 0% terkonfirmasi" vs "belum ada data sama sekali"."""
    import statistics
    from collections import defaultdict
    try:
        countries, regions_obj = raw_data if raw_data is not None else await get_bonus_raw_data(session, with_cache=with_cache)
        countries_by_id = {c["_id"]: c for c in countries if c.get("_id")}
        if parties_by_id is None:
            party_ids = list({c.get("rulingParty") for c in countries_by_id.values() if c.get("rulingParty")})
            parties_by_id = await _fetch_parties_batch(session, party_ids)

        now = datetime.now(timezone.utc)
        totals_by_item: dict[str, list[float]] = defaultdict(list)
        if regions_obj:
            for region in regions_obj.values():
                if not region:
                    continue
                country_id = region.get("country")
                country    = countries_by_id.get(country_id) if country_id else None
                party      = parties_by_id.get(country.get("rulingParty")) if country else None
                for item_id in ITEM_LABELS:
                    total = _country_bonus_pct(country, item_id, party) + _deposit_bonus_pct(region, item_id, party, now)
                    totals_by_item[item_id].append(total)
        else:
            for country in countries_by_id.values():
                party = parties_by_id.get(country.get("rulingParty"))
                for item_id in ITEM_LABELS:
                    total = _country_bonus_pct(country, item_id, party)
                    totals_by_item[item_id].append(total)

        out: dict[str, float] = {}
        for item_id in ITEM_LABELS:
            population_b = [t for t in totals_by_item.get(item_id, []) if t > 0]
            median_pct = statistics.median(population_b) if population_b else 0.0
            out[_label(item_id)] = round(median_pct, 2)
        return out
    except Exception as exc:
        log.error(f"fetch_median_bonuses: {exc}")
        return {}


async def fetch_bonus_breakdown(
    session: aiohttp.ClientSession, top_n: int = 2, with_cache: bool = False, force_refresh: bool = False,
    raw_data: Optional[tuple[list[dict], dict]] = None,
    parties_by_id: Optional[dict[str, dict]] = None,
) -> dict[str, list[tuple[str, float]]]:
    """Top-N negara dengan bonus produksi tertinggi per item, dipake xitem
    buat nunjukin "top 2 bonus + lokasinya". Beda dari fetch_max_bonuses yang
    cuma nyimpen 1 angka tanpa nama negara.

    Return: {item_label: [(country_name, pct), ...]} urut desc, max top_n."""
    from collections import defaultdict
    try:
        countries, regions_obj = raw_data if raw_data is not None else await get_bonus_raw_data(session, with_cache=with_cache, force_refresh=force_refresh)
        countries_by_id = {c["_id"]: c for c in countries if c.get("_id")}
        if parties_by_id is None:
            party_ids = list({c.get("rulingParty") for c in countries_by_id.values() if c.get("rulingParty")})
            parties_by_id = await _fetch_parties_batch(session, party_ids)

        now = datetime.now(timezone.utc)
        per_item_country: dict[str, dict[str, float]] = defaultdict(dict)

        def _consider(item_id: str, country: dict, total: float) -> None:
            if total <= 0:
                return
            name = country.get("name", "Unknown")
            bucket = per_item_country[item_id]
            if total > bucket.get(name, 0):
                bucket[name] = total

        if regions_obj:
            for region in regions_obj.values():
                if not region:
                    continue
                country_id = region.get("country")
                country = countries_by_id.get(country_id) if country_id else None
                if not country:
                    continue
                party = parties_by_id.get(country.get("rulingParty"))
                for item_id in ITEM_LABELS:
                    total = _country_bonus_pct(country, item_id, party) + _deposit_bonus_pct(region, item_id, party, now)
                    _consider(item_id, country, total)
        else:
            for country in countries_by_id.values():
                party = parties_by_id.get(country.get("rulingParty"))
                for item_id in ITEM_LABELS:
                    total = _country_bonus_pct(country, item_id, party)
                    _consider(item_id, country, total)

        out: dict[str, list[tuple[str, float]]] = {}
        for item_id, country_map in per_item_country.items():
            ranked = sorted(country_map.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
            out[_label(item_id)] = [(name, round(pct, 2)) for name, pct in ranked]
        return out
    except Exception as exc:
        log.error(f"fetch_bonus_breakdown: {exc}")
        return {}


async def fetch_bonus_deposit_ends(
    session: aiohttp.ClientSession,
    breakdown: dict[str, list[tuple[str, float]]],
    with_cache: bool = False,
    raw_data: Optional[tuple[list[dict], dict]] = None,
    parties_by_id: Optional[dict[str, dict]] = None,
) -> dict[str, dict[str, datetime]]:
    """Waktu berakhir deposit yang menyumbang bonus di bonus_breakdown — dipakai
    xitem buat nampilin durasi. Cuma deposit yang punya endsAt; bonus negara &
    partai gak punya masa berlaku di API, jadi gak masuk sini. Region penyumbang
    dipilih pakai logika yang sama dengan fetch_bonus_breakdown (total tertinggi).

    Return: {item_label: {country_name: ends_at (UTC)}}. Struktur bonus_breakdown
    sendiri sengaja gak diubah biar pemakai lain (web, workerprofit, tax) aman."""
    try:
        countries, regions_obj = raw_data if raw_data is not None else await get_bonus_raw_data(session, with_cache=with_cache)
        countries_by_name = {c["name"]: c for c in countries if c.get("name")}
        if parties_by_id is None:
            party_ids = list({c.get("rulingParty") for c in countries if c.get("rulingParty")})
            parties_by_id = await _fetch_parties_batch(session, party_ids)

        regions_by_country: dict[str, list[dict]] = {}
        for region in (regions_obj or {}).values():
            if region and region.get("country"):
                regions_by_country.setdefault(region["country"], []).append(region)

        label_to_id = {_label(item_id): item_id for item_id in ITEM_LABELS}
        now = datetime.now(timezone.utc)
        out: dict[str, dict[str, datetime]] = {}
        for label, entries in breakdown.items():
            item_id = label_to_id.get(label)
            if not item_id:
                continue
            for country_name, _pct in entries:
                country = countries_by_name.get(country_name)
                if not country:
                    continue
                party = parties_by_id.get(country.get("rulingParty"))
                base = _country_bonus_pct(country, item_id, party)
                best_total, best_end = 0.0, None
                for region in regions_by_country.get(country.get("_id"), []):
                    deposit_pct = _deposit_bonus_pct(region, item_id, party, now)
                    if deposit_pct <= 0:
                        continue
                    if base + deposit_pct > best_total:
                        best_total = base + deposit_pct
                        best_end = (region.get("deposit") or {}).get("endsAt")
                if not best_end:
                    continue
                try:
                    ends_at = datetime.fromisoformat(str(best_end).replace("Z", "+00:00"))
                except ValueError:
                    continue
                out.setdefault(label, {})[country_name] = ends_at
        return out
    except Exception as exc:
        log.error(f"fetch_bonus_deposit_ends: {exc}")
        return {}


async def fetch_country_tax_breakdown(
    session: aiohttp.ClientSession,
    bonus_breakdown: dict[str, list[tuple[str, float]]],
    with_cache: bool = False,
) -> dict[str, float]:
    """Income tax cuma buat negara yang muncul di bonus_breakdown (bukan
    semua negara) — dipake xitem buat nampilin income tax di samping bonus
    produksi tiap negara.

    country.getAllCountries gak reliable nyediain field taxes, jadi diambil
    terpisah lewat country.getCountryById per negara. Di-cache (key
    "country_tax", TTL sama _CACHE_TTL_BONUS) biar gak fetch ulang negara
    yang sama tiap refresh cycle.

    Return: {country_name: income_tax_pct}"""
    try:
        countries, _ = await get_bonus_raw_data(session, with_cache=with_cache)
        name_to_id = {c.get("name"): c.get("_id") for c in countries if c.get("name") and c.get("_id")}

        unique_names: set[str] = {
            name for entries in bonus_breakdown.values() for name, _pct in entries
        }
        if not unique_names:
            return {}

        cached = await _load_cache_row(with_cache, "country_tax", _CACHE_TTL_BONUS)
        tax_by_name: dict[str, float] = dict(cached) if cached else {}

        missing_names = [n for n in unique_names if n not in tax_by_name]
        for name in missing_names:
            country_id = name_to_id.get(name)
            if not country_id:
                continue
            detail = await fetch_country_by_id(session, country_id, rate_limiter=_tax_limiter)
            if not detail:
                continue
            income = (detail.get("taxes") or {}).get("income")
            if income is None:
                continue
            tax_by_name[name] = round(float(income), 2)

        if missing_names:
            await _save_cache_row(with_cache, "country_tax", tax_by_name)
            fetched_ok = sum(1 for n in missing_names if n in tax_by_name)
            if fetched_ok < len(missing_names):
                log.warning(
                    f"fetch_country_tax_breakdown: {len(missing_names) - fetched_ok}/"
                    f"{len(missing_names)} negara baru GAGAL di-fetch (429/network/no "
                    f"income field) — akan dicoba lagi cycle berikutnya."
                )

        return {n: tax_by_name[n] for n in unique_names if n in tax_by_name}
    except Exception as exc:
        log.error(f"fetch_country_tax_breakdown: {exc}")
        return {}


def _search_country_by_name(countries: list[dict], query: str) -> tuple[str, str] | None:
    for c in countries:
        if c.get("name", "").lower() == query:
            return (c["_id"], c["name"])
    for c in countries:
        if query in c.get("name", "").lower():
            return (c["_id"], c["name"])
    return None


async def fetch_country_id_by_name(
    session: aiohttp.ClientSession,
    country_name: str,
    headers: Optional[dict] = None,
    with_cache: bool = False,
) -> tuple[str, str] | None:
    """Resolve nama negara -> (country_id, country_name resmi). Pake cache
    bersama get_country_list (TTL 1 bulan), gak fetch API langsung tiap
    dipanggil.

    Kalau nama gak ketemu di cache, lazy-rescan sekali ke API sebelum
    declare "tidak ditemukan" — biar rename negara ke-detect tanpa nunggu
    TTL habis atau restart bot manual."""
    try:
        query = country_name.strip().lower()

        countries = await get_country_list(session, with_cache=with_cache, headers=headers)
        found = _search_country_by_name(countries, query)
        if found:
            return found

        countries = await get_country_list(session, with_cache=with_cache, headers=headers, force_refresh=True)
        return _search_country_by_name(countries, query)
    except Exception as exc:
        log.error(f"fetch_country_id_by_name({country_name}): {exc}")
        return None


async def fetch_country_by_id(
    session: aiohttp.ClientSession,
    country_id: str,
    rate_limiter: "Optional[_RateLimiter]" = None,
) -> dict | None:
    """Data 1 negara langsung dari country.getCountryById — dipake khusus
    buat ambil taxes (income/market/selfWork) yang akurat, krna
    country.getAllCountries gak reliable nyediain field ini.

    rate_limiter opsional: kalau diisi, request dipacing proaktif selain
    retry-backoff — dipake pemanggil beruntun (fetch_country_tax_breakdown)
    biar gak nembak API tanpa jeda. Caller tunggal yang gak kasih
    rate_limiter tetep dapet retry-backoff otomatis, cuma tanpa pacing-nya."""
    try:
        url = f"{COUNTRY_BY_ID_URL}?input={_encode({'countryId': country_id})}"
        result = await _get_json_with_retry(
            session, url, headers=_auth_headers(), timeout=10, rate_limiter=rate_limiter,
        )
        return result["result"]["data"]
    except Exception as exc:
        log.error(f"fetch_country_by_id({country_id}): {exc}")
        return None
