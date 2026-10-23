# services/spy/api_client.py — HTTP client WarEra untuk SpyCog (diekstrak 28 Sep 2026)

from __future__ import annotations

import json
import logging
import urllib.parse

log = logging.getLogger("WarEraBot.api_client")


# --- core ---

async def api_get(session, path: str, params: dict) -> dict | None:
    """HTTP GET ke WarEra API, return field result.data."""
    import market as mkt
    encoded = urllib.parse.quote(json.dumps(params, separators=(",", ":")))
    url = f"{mkt.BASE_URL}/{path}?input={encoded}"

    try:
        resp = await mkt._get_json_with_retry(session, url, headers=mkt.HEADERS, timeout=10)
        return resp["result"]["data"]
    except Exception as exc:
        log.error(f"api_get({path}): {type(exc).__name__}: {exc!r}")
        return None


# --- wrapper endpoint ---

async def search_user_ids(session, query: str) -> list[str]:
    """Cari user IDs dari query teks."""
    data = await api_get(session, "search.searchAnything", {"searchText": query})
    if not data:
        return []
    return data.get("userIds", [])


async def get_user_lite(session, user_id: str) -> dict | None:
    """Data user lite (getUserLite)."""
    return await api_get(session, "user.getUserLite", {"userId": user_id})


async def get_company(session, company_id: str) -> dict | None:
    """Detail 1 company (company.getById)."""
    return await api_get(session, "company.getById", {"companyId": company_id})


async def get_mu(session, mu_id: str) -> dict | None:
    """Detail 1 MU (mu.getById)."""
    return await api_get(session, "mu.getById", {"muId": mu_id})


async def get_mu_upgrade(session, mu_id: str, upgrade_type: str) -> dict | None:
    """Fetch upgrade data MU: headquarters, dormitories, dll."""
    return await api_get(session,
        "upgrade.getUpgradeByTypeAndEntity",
        {"upgradeType": upgrade_type, "muId": mu_id}
    )


async def get_alliance(session, alliance_id: str) -> dict | None:
    """Detail 1 alliance (alliance.getById)."""
    return await api_get(session, "alliance.getById", {"allianceId": alliance_id})


# --- direct HTTP (butuh X-Api-Key) ---

async def get_wage_info(session, user_id: str) -> dict | None:
    """Ambil 1 transaksi wage terakhir milik user_id.
    Return: gold, pp, gold_per_pp, company_id, company_name, boss_name."""
    import market as mkt
    params = {
        "userId": user_id,
        "transactionType": "wage",
        "limit": 1,
    }
    url = f"{mkt.TRANSACTION_URL}?input={mkt._encode(params)}"
    try:
        resp = await mkt._get_json_with_retry(session, url, headers=mkt._auth_headers(), timeout=15)
        data = resp["result"]["data"]
    except Exception as exc:
        log.error(f"get_wage_info: {type(exc).__name__}: {exc!r}")
        return None

    items = data.get("items", [])
    if not items:
        return None

    tx = items[0]
    money = float(tx.get("money") or 0)
    quantity = float(tx.get("quantity") or 0)
    if quantity <= 0:
        return None

    gold_per_pp = money / quantity
    company_id = tx.get("buyerId")
    company_name = None
    boss_name = None

    if company_id:
        company_data = await get_company(session, company_id)
        if company_data:
            company_name = company_data.get("name")
            owner_id = company_data.get("owner")
            if owner_id:
                boss_data = await get_user_lite(session, owner_id)
                if boss_data:
                    boss_name = boss_data.get("username")

    return {
        "gold": money,
        "pp": quantity,
        "gold_per_pp": gold_per_pp,
        "company_id": company_id,
        "company_name": company_name,
        "boss_name": boss_name,
    }


async def get_current_equipment(session, user_id: str) -> dict | None:
    """Data equipment mentah per-slot (chest/pants/gloves/boots/weapon
    terpisah, tidak digabung) via inventory.fetchCurrentEquipment.
    Beda dari get_user_lite: endpoint ini butuh API token (X-Api-Key),
    jadi dipanggil terpisah, bukan lewat api_get biasa."""
    import market as mkt
    params = {"userId": user_id}
    encoded = urllib.parse.quote(json.dumps(params, separators=(",", ":")))
    url = f"{mkt.BASE_URL}/inventory.fetchCurrentEquipment?input={encoded}"
    try:
        resp = await mkt._get_json_with_retry(session, url, headers=mkt._auth_headers(), timeout=10)
        return resp["result"]["data"]
    except Exception as exc:
        log.error(f"get_current_equipment({user_id}): {type(exc).__name__}: {exc!r}")
        return None


async def get_owned_companies(session, user_id: str) -> list[dict]:
    """Ambil company milik user_id lewat on-demand live fetch ke API
    (bukan baca-pasif dari cache background scan lagi -- background scan
    full-company sudah dinonaktifkan, lihat cogs/spy/api/company_scan.py).

    Filter userId di company.getCompanies terverifikasi bekerja di sisi
    server (lihat market.fetch_and_cache_user_companies), jadi hasil di
    sini selalu lengkap & real-time per panggilan -- bukan lagi data
    indikatif yang bisa ketinggalan sampai scan 3-jam berikutnya.

    Hasil fetch otomatis di-upsert ke company_index (app_db) di dalam
    market.fetch_and_cache_user_companies -- baris yang di-return di sini
    sudah final, tidak perlu baca ulang dari cache.
    """
    import market as mkt
    try:
        return await mkt.fetch_and_cache_user_companies(session, user_id)
    except Exception as exc:
        log.error(f"get_owned_companies({user_id}): {exc}")
        return []
