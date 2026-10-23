"""cogs/spy/api/wealth.py — analitik ledger transaksi: rekonsiliasi wealth
(xspy check), FIFO win-rate trading (xspy trade), estimasi live tax negara
(xspy country). Dipecah dari api.py (dulu 1 file 1175 baris)."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone, timedelta

from ..constants import (
    TX_PAGE_LIMIT,
    TX_MAX_PAGES,
    GOLD_TX_TYPES,
    ITEM_ONLY_TX_TYPES,
    UNRESOLVED_TX_TYPES,
    TAX_ESTIMATE_MAX_COMPANIES,
    WORKER_FETCH_CONCURRENCY,
    ENERGY_HOURS_PER_DAY,
    CLICK_ENERGY_COST,
)
from services.spy.utils import tx_money_delta
from services.spy.api_client import get_user_lite

log = logging.getLogger("WarEraBot.spy")


class WealthMixin:
    """Mixin — expects self._session dari class final (SpyCog di __init__.py,
    lewat CompanyScanMixin)."""

    # --- xspy check: rekonsiliasi ledger transaksi asli ---

    async def _fetch_wealth_reconciliation(self, user_id: str, since_dt: datetime) -> dict:
        import market as mkt

        cursor: str | None = None
        net_gold = 0.0
        breakdown: dict[str, float] = {}
        item_counts: dict[str, int] = {}
        unresolved: dict[str, float] = {}
        unresolved_count: dict[str, int] = {}
        unknown_types: set[str] = set()
        pages = 0
        capped = False
        reached_cutoff = False

        for _ in range(TX_MAX_PAGES):
            params: dict = {"userId": user_id, "limit": TX_PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            url = f"{mkt.TRANSACTION_URL}?input={mkt._encode(params)}"
            try:
                resp = await mkt._get_json_with_retry(self._session, url, headers=mkt._auth_headers(), timeout=15)
                data = resp["result"]["data"]
            except Exception as exc:
                log.error(f"_fetch_wealth_reconciliation: {type(exc).__name__}: {exc!r}, stop.")
                break

            items = data.get("items", [])
            if not items:
                break

            pages += 1
            stop_here = False
            for it in items:
                created_at = it.get("createdAt")
                try:
                    tx_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None
                except Exception:
                    tx_dt = None
                if tx_dt and tx_dt < since_dt:
                    stop_here = True
                    break

                t = it.get("transactionType", "?")
                if t in GOLD_TX_TYPES:
                    delta = tx_money_delta(it, user_id)
                    net_gold += delta
                    breakdown[t] = breakdown.get(t, 0.0) + delta
                elif t in ITEM_ONLY_TX_TYPES:
                    item_counts[t] = item_counts.get(t, 0) + 1
                elif t in UNRESOLVED_TX_TYPES:
                    unresolved[t] = unresolved.get(t, 0.0) + float(it.get("money") or 0)
                    unresolved_count[t] = unresolved_count.get(t, 0) + 1
                else:
                    unknown_types.add(t)

            if stop_here:
                reached_cutoff = True
                break

            cursor = data.get("nextCursor")
            if not cursor:
                break
        else:
            capped = True

        return {
            "net_gold": net_gold,
            "breakdown": breakdown,
            "item_counts": item_counts,
            "unresolved": unresolved,
            "unresolved_count": unresolved_count,
            "unknown_types": unknown_types,
            "pages_fetched": pages,
            "capped": capped,
            "reached_cutoff": reached_cutoff,
        }

    # --- xspy trade: FIFO win-rate per player ---
    # --- xspy country: live tax estimate ---

    async def _estimate_country_tax(
        self, company_rows: list[dict], tax_rate_pct: float
    ) -> tuple[float, int, int]:
        import market as mkt

        rows = company_rows[:TAX_ESTIMATE_MAX_COMPANIES]
        sem = asyncio.Semaphore(WORKER_FETCH_CONCURRENCY)

        async def _company_workers(cid: str) -> list[dict]:
            async with sem:
                res = await mkt.fetch_workers(self._session, cid)
                # None = fetch gagal — perlakukan sebagai kosong untuk
                # estimasi pajak (bukan data valid), tapi tetap log.
                if res is None:
                    log.warning(f"tax estimate: fetch_workers({cid}) gagal (None) — company dilewati")
                    return []
                return res

        worker_lists = await asyncio.gather(*[_company_workers(r["company_id"]) for r in rows])
        all_workers = [w for wl in worker_lists for w in wl]

        unique_user_ids = list({w.get("user") for w in all_workers if w.get("user")})

        async def _user_stats(uid: str) -> tuple[str, dict | None]:
            async with sem:
                data = await get_user_lite(self._session, uid)
                return uid, data

        user_results = await asyncio.gather(*[_user_stats(uid) for uid in unique_user_ids])
        user_data = {uid: data for uid, data in user_results if data}

        total_gross_daily = 0.0
        workers_counted = 0

        for w in all_workers:
            uid = w.get("user")
            wage = float(w.get("wage") or 0)
            ud = user_data.get(uid)
            if not ud or wage <= 0:
                continue

            skills = ud.get("skills", {})
            pp = float(skills.get("production", {}).get("total") or 0)
            energy_obj = skills.get("energy", {})
            energy_max = float(energy_obj.get("value") or energy_obj.get("total") or 0)
            regen_pct = float(energy_obj.get("hourlyBarRegen") or 0)

            if pp <= 0 or energy_max <= 0 or regen_pct <= 0:
                continue

            clicks_per_day = (energy_max * (regen_pct / 100) * ENERGY_HOURS_PER_DAY) / CLICK_ENERGY_COST
            gross_per_click = wage * pp
            gross_daily = gross_per_click * clicks_per_day

            total_gross_daily += gross_daily
            workers_counted += 1

        tax_daily = total_gross_daily * (tax_rate_pct / 100)
        return tax_daily, len(rows), workers_counted
