# company_bonus.py
"""Company milik user + bonus produksi per-region (shared).

Diekstrak dari cogs/economy/dailyprofit.py::_resolve_companies_with_bonus
(Fase 6b): satu sumber kebenaran dipakai Discord cog & webapp builder.
Bonus = country bonus + deposit bonus per region (data riil dari API),
bukan angka tebakan.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from services.economy.constants import PRODUCTION_CHAIN

log = logging.getLogger("bwabwabot.company_bonus")


async def resolve_companies_with_bonus(session, user_id: str) -> list[dict]:
    """Company milik user_id + bonus produksi per-region.

    AE 0/kosong -> 1. Item tak dikenali ditandai known=False, tetap masuk
    list tapi exclude dari hitungan PP. Return per company: company_id,
    owner_id, name, region_id, raw_item_code, item_label (None kalau tak
    dikenal), known, ae_level, worker_count, bonus_pct.
    """
    import market as mkt  # lazy: hindari circular import (pola api_client)

    rows = await mkt.fetch_and_cache_user_companies(session, user_id)
    if not rows:
        return []

    countries, regions_obj = await mkt.get_bonus_raw_data(session, with_cache=True)
    countries_by_id = {c["_id"]: c for c in countries if c.get("_id")}

    party_ids = list({
        countries_by_id.get((regions_obj.get(r.get("region_id")) or {}).get("country"), {}).get("rulingParty")
        for r in rows
    } - {None})
    parties_by_id = await mkt._fetch_parties_batch(session, party_ids)

    now = datetime.now(timezone.utc)
    out = []
    for row in rows:
        ae_level = int(row.get("ae_level") or 0) or 1  # fallback kalau data API null

        raw_code = row.get("item_code") or ""
        item_id = mkt.API_KEY_TO_ITEM_ID.get(raw_code, raw_code)
        label = mkt.ITEM_LABELS.get(item_id, item_id)
        known = label in PRODUCTION_CHAIN

        region = regions_obj.get(row.get("region_id")) or {}
        country_id = region.get("country")
        country = countries_by_id.get(country_id)
        party = parties_by_id.get(country.get("rulingParty")) if country else None

        bonus_pct = 0.0
        if known:
            bonus_pct = round(
                mkt._country_bonus_pct(country, item_id, party)
                + mkt._deposit_bonus_pct(region, item_id, party, now),
                6,
            )

        out.append({
            "company_id": row.get("company_id"),
            "owner_id": row.get("owner_id"),
            "name": row.get("name") or "",
            "region_id": row.get("region_id"),
            "raw_item_code": raw_code,
            "item_label": label if known else None,
            "known": known,
            "ae_level": ae_level,
            "worker_count": int(row.get("worker_count") or 0),
            "bonus_pct": bonus_pct,
        })
    return out
