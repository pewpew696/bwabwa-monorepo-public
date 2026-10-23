"""Helper bersama Hub Intel: fetch tx paginated + clean/sort.

Port dari web_api/hub_intel.py. Dipakai bareng C2 (country-stock) dan
C3 (top-traders) — jangan reimplementasi per fitur.
"""
import asyncio
import logging
from datetime import datetime

import market

log = logging.getLogger("WarEraBot.hub_intel_helpers")

TX_PAGE_LIMIT = 100
TX_MAX_PAGES_COUNTRY = 300
TX_MAX_PAGES_USER = 10_000_000
PAGE_SLEEP_S = 0.25


def _parse_dt(iso):
    """Port dari web_api/hub_intel.py::_parse_dt."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None


async def _fetch_transactions(session, country_id=None, user_id=None, since_dt=None, max_pages=TX_MAX_PAGES_USER):
    """Port dari web_api/hub_intel.py::_fetch_transactions.

    Fetch tx itemMarket + trading (countryId ATAU userId).
    """
    all_tx = []

    tx_types = ("itemMarket", "trading") if country_id else ("trading", "itemMarket")

    for tx_type in tx_types:
        cursor = None
        for _page in range(max_pages):
            params = {"transactionType": tx_type, "limit": TX_PAGE_LIMIT}
            if country_id:
                params["countryId"] = country_id
            if user_id:
                params["userId"] = user_id
            if cursor:
                params["cursor"] = cursor

            url = f"{market.TRANSACTION_URL}?input={market._encode(params)}"

            try:
                raw = await market._get_json_with_retry(
                    session, url, market._hub_auth_headers(), timeout=20, max_retries=3
                )
            except Exception as e:
                log.error(f"[HUBINTEL] _fetch_transactions FAILED tx_type={tx_type} page={_page}: {e!r}")
                break

            data = raw.get("result", {}).get("data", {}) if isinstance(raw, dict) else {}

            items = data.get("items", [])
            if not items:
                break

            all_tx.extend(items)

            if since_dt is not None:
                oldest_in_page = _parse_dt(items[-1].get("createdAt"))
                if oldest_in_page and oldest_in_page < since_dt:
                    break

            cursor = data.get("nextCursor")
            if not cursor:
                break

            await asyncio.sleep(PAGE_SLEEP_S)

    return all_tx


def _clean_and_sort(all_tx, since_dt):
    """Port dari web_api/hub_intel.py::_clean_and_sort."""
    for it in all_tx:
        it["_dt"] = _parse_dt(it.get("createdAt"))
    all_tx = [it for it in all_tx if it.get("itemCode") and it.get("quantity") and it.get("_dt")]
    if since_dt is not None:
        all_tx = [it for it in all_tx if it["_dt"] >= since_dt]
    all_tx.sort(key=lambda it: it["_dt"])
    return all_tx
