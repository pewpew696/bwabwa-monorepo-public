"""
cogs/spy/workers.py — `xspy workers` (admin-only, on-demand).

Input: username. Output: semua company milik user yang PUNYA worker,
disertai storage % pabrik, lalu daftar worker (username, current energy,
last seen) di bawah tiap pabrik. Company tanpa worker di-skip.

WorkersMixin butuh ApiMixin (self._search_user_ids, self._get_user_lite,
self._api_get, self._session) dan disatukan ke SpyCog di __init__.py,
sama seperti mixin lain di package ini.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from .api import _bot_admin_check
from core.utils import make_embed
from services.spy.utils import last_seen, not_found_msg
from services.spy.search import find_player_exact
from services.spy.api_client import api_get, get_user_lite

log = logging.getLogger("WarEraBot.spy")

WORKERS_FETCH_CONCURRENCY = 10
STORAGE_CAPACITY_BY_LEVEL = {1: 200, 2: 400, 3: 600, 4: 800, 5: 1000, 6: 1200, 7: 1400}


class WorkersMixin:
    """Mixin — expects ApiMixin di final class (self._search_user_ids,
    self._get_user_lite, self._api_get, self._session)."""

    async def _get_company_storage_pct(self, company_id: str) -> dict | None:
        c = await api_get(self._session, "company.getById", {"companyId": company_id})
        if not c:
            return None
        level = c.get("activeUpgradeLevels", {}).get("storage", 1)
        capacity = STORAGE_CAPACITY_BY_LEVEL.get(level, max(STORAGE_CAPACITY_BY_LEVEL.values()))
        # ⚠️ asumsi "production" = isi storage saat ini — sama asumsi yang
        # dipakai poll_storage.py, belum diverifikasi manual ulang di sini.
        storage_pct = round(c.get("production", 0) / capacity * 100, 1)
        return {
            "name": c.get("name", company_id),
            "item": c.get("itemCode", "?"),
            "storage_pct": storage_pct,
            "region": c.get("region"),
        }

    async def _load_country_tax_map(self) -> dict[str, float]:
        """Fetch regions + countries sekali per command run, balikin
        mapping region_id -> income_tax_pct (untuk hitung wage bersih)."""
        import market as mkt

        try:
            regions_obj = await mkt.get_regions_object(self._session, with_cache=True)
        except Exception as exc:
            log.warning(f"spy_workers regions fetch: {type(exc).__name__}: {exc!r}")
            regions_obj = {}

        try:
            resp = await mkt._get_json_with_retry(self._session, mkt.COUNTRIES_URL, headers=mkt.HEADERS, timeout=15)
            countries_list = resp["result"]["data"] or []
        except Exception as exc:
            log.warning(f"spy_workers countries fetch: {type(exc).__name__}: {exc!r}")
            countries_list = []

        tax_by_country_id = {
            c["_id"]: (c.get("taxes") or {}).get("income")
            for c in countries_list if c.get("_id")
        }

        region_to_tax: dict[str, float] = {}
        for region_id, rdata in regions_obj.items():
            country_id = (rdata or {}).get("country")
            tax_pct = tax_by_country_id.get(country_id)
            if tax_pct is not None:
                region_to_tax[region_id] = tax_pct

        return region_to_tax

    async def _get_company_workers(self, company_id: str) -> list[dict] | None:
        import market as mkt
        return await mkt.fetch_workers(self._session, company_id)

    @commands.command(name="workers", aliases=["w"])
    @commands.check(_bot_admin_check)
    async def spy_workers(self, ctx: commands.Context, *, nama: str) -> None:
        """Admin-only: tampilkan semua pabrik user yang punya worker,
        beserta storage % dan daftar worker (energy + last seen).
        Example: xspy workers Vincapervinca"""
        async with ctx.typing():
            user_data, suggestions = await find_player_exact(self._session, nama)
            if not user_data:
                await ctx.send(f"⚠️ {not_found_msg('Player', nama, suggestions, md=True)}")
                return
            user_id = user_data["_id"]

            company_data = await api_get(self._session, "company.getCompanies", {"userId": user_id})
            company_ids = (company_data or {}).get("items", [])
            if not company_ids:
                await ctx.send(f"ℹ️ `{nama}` has no company.")
                return

            sem = asyncio.Semaphore(WORKERS_FETCH_CONCURRENCY)

            async def _load_company(cid: str) -> tuple[dict | None, list[dict] | None]:
                async with sem:
                    info = await self._get_company_storage_pct(cid)
                    workers = await self._get_company_workers(cid)
                    return info, workers

            results = await asyncio.gather(*[_load_company(cid) for cid in company_ids])

            companies_with_workers = [(info, workers) for info, workers in results if info and workers]

            if not companies_with_workers:
                await ctx.send(f"ℹ️ `{nama}` has no factory with active workers.")
                return

            region_to_tax = await self._load_country_tax_map()

            unique_worker_ids = list({
                w.get("user") for _, workers in companies_with_workers for w in workers if w.get("user")
            })

            async def _user_stats(uid: str) -> tuple[str, dict | None]:
                async with sem:
                    data = await get_user_lite(self._session, uid)
                    return uid, data

            user_results = await asyncio.gather(*[_user_stats(uid) for uid in unique_worker_ids])
            user_data = {uid: data for uid, data in user_results if data}

        e = make_embed(f"🏭 Workers: {nama}", discord.Color.blurple())

        for info, workers in companies_with_workers:
            lines = []
            tax_pct = region_to_tax.get(info.get("region"))
            for w in workers:
                uid = w.get("user")
                ud = user_data.get(uid)
                if not ud:
                    lines.append(f"**`{uid or '?'}`**\n`⚠️ data not found`")
                    continue
                uname = ud.get("username", "?")
                energy_obj = ud.get("skills", {}).get("energy", {})
                energy_cur = energy_obj.get("currentBarValue", "?")
                energy_total = energy_obj.get("total", "?")
                seen = last_seen(ud.get("dates", {}))
                energy_str = f"{energy_cur}/{energy_total}"

                wage_gross = w.get("wage")
                if wage_gross is not None and tax_pct is not None:
                    net_wage = wage_gross * (1 - tax_pct / 100)
                    wage_str = f"{net_wage:.3f}/PP"
                elif wage_gross is not None:
                    wage_str = f"{wage_gross:.3f}/PP (gross)"
                else:
                    wage_str = "-"

                lines.append(
                    f"**{uname}**\n"
                    f"`🕒 {seen:>9}  ⚡ {energy_str:>9}  💰 {wage_str}`"
                )

            tax_str = f" — 💰 tax {tax_pct}%" if tax_pct is not None else ""
            field_name = f"{info['name']} ({info['item']}) — 📦 {info['storage_pct']}%{tax_str}"
            e.add_field(name=field_name, value="\n".join(lines) or "-", inline=False)

        await ctx.send(embed=e)

    @spy_workers.error
    async def spy_workers_error(self, ctx: commands.Context, error: Exception) -> None:
        from core.utils import ChannelNotAllowed
        if isinstance(error, ChannelNotAllowed):
            return
        if isinstance(error, commands.CheckFailure):
            return  # diam-diam gagal, konsisten dgn command admin-only lain
        log.error(f"spy_workers error: {error}", exc_info=True)
        await ctx.send("❌ An error occurred.")
