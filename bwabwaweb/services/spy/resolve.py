# services/spy/resolve.py — resolve ID -> nama (diekstrak 28 Sep 2026)

from __future__ import annotations

import logging

log = logging.getLogger("WarEraBot.resolve")


# --- resolver ---

async def resolve_mu_name(session, mu_id: str | None) -> str:
    """Nama MU dari ID."""
    from services.spy.api_client import get_mu
    if not mu_id:
        return "\u2014"
    data = await get_mu(session, mu_id)
    if data:
        return data.get("name", mu_id[:8] + "...")
    return mu_id[:8] + "..."


async def resolve_alliance_name(session, alliance_id: str | None) -> str:
    """Nama alliance dari ID."""
    from services.spy.api_client import get_alliance
    if not alliance_id:
        return "\u2014"
    data = await get_alliance(session, alliance_id)
    if data:
        return data.get("name", alliance_id[:8] + "...")
    return alliance_id[:8] + "..."


async def resolve_country_name(session, country_id: str | None) -> str:
    """Nama negara dari ID."""
    if not country_id:
        return "\u2014"
    import market as mkt
    try:
        resp = await mkt._get_json_with_retry(session, mkt.COUNTRIES_URL, headers=mkt.HEADERS, timeout=15)
        countries_list = resp["result"]["data"] or []
    except Exception as exc:
        log.error(f"resolve_country_name: {type(exc).__name__}: {exc!r}")
        return country_id[:8] + "..."

    country = next((c for c in countries_list if c.get("_id") == country_id), None)
    if country:
        return country.get("name", country_id[:8] + "...")
    return country_id[:8] + "..."
