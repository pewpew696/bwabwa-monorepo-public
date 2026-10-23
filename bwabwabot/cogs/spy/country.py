"""
cogs/spy/country.py — `xspy country`.

CountryMixin butuh ApiMixin (self._get_user_lite, self._resolve_alliance_name,
self._session). Command didefinisikan lepas (@commands.command)
lalu disambungkan ke group `xspy` secara manual di __init__.py.
"""

from __future__ import annotations

import asyncio
from services.spy.api_client import get_user_lite
from services.spy.resolve import resolve_alliance_name
import logging
import time

import discord
from discord.ext import commands

from .constants import ITEM_EMOJI
from core.utils import make_embed
from services.spy.utils import fmt_k, ago

log = logging.getLogger("WarEraBot.spy")


class CountryMixin:
    """Mixin — expects ApiMixin di final class."""

    @commands.command(name="country", aliases=["c"])
    async def spy_country(self, ctx: commands.Context, *, nama: str) -> None:
        """Country intel. Example: xspy country Laos"""
        import market as mkt

        async with ctx.typing():
            result = await mkt.fetch_country_id_by_name(self._session, nama)
            if not result:
                await ctx.send(f"⚠️ Country `{nama}` not found.")
                return
            country_id, country_name = result

            try:
                resp = await mkt._get_json_with_retry(self._session, mkt.COUNTRIES_URL, headers=mkt.HEADERS, timeout=15)
                countries_list = resp["result"]["data"] or []
            except Exception as exc:
                log.error(f"spy_country countries fetch: {type(exc).__name__}: {exc!r}")
                await ctx.send("❌ Failed to fetch country data.")
                return

            country = next((c for c in countries_list if c.get("_id") == country_id), None)
            if not country:
                await ctx.send("❌ Country data not found.")
                return

            try:
                regions_obj = await mkt.get_regions_object(self._session, with_cache=True)
            except Exception as exc:
                log.error(f"spy_country regions fetch: {type(exc).__name__}: {exc!r}")
                regions_obj = {}

            region_ids = [
                rid for rid, rdata in regions_obj.items()
                if rdata and rdata.get("country") == country_id
            ]

            company_rows: list[dict] = []
            cache_age_str = "never scanned"
            if region_ids:
                from services.spy import cache_store as spy_store
                try:
                    company_rows = await asyncio.to_thread(spy_store.get_companies_by_regions, region_ids)
                    if company_rows:
                        latest = max(
                            (r.get("updated_at") for r in company_rows if r.get("updated_at")),
                            default=None,
                        )
                        cache_age_str = ago(latest)
                except Exception as exc:
                    log.warning(f"spy_country company_index query: {exc}")

            # PENTING: item_code di company_index tersimpan format API mentah
            # (mis. "coca"), BUKAN item_id internal ("mysterious_plant"). Wajib
            # convert lewat API_KEY_TO_ITEM_ID dulu sebelum lookup label, kalau
            # tidak label bakal salah tampil (mis. "coca" apa adanya).
            item_counts: dict[str, int] = {}
            for row in company_rows:
                raw_code = row.get("item_code") or "?"
                item_id = mkt.API_KEY_TO_ITEM_ID.get(raw_code, raw_code)
                item_counts[item_id] = item_counts.get(item_id, 0) + 1
            top_items = sorted(item_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]

            gov = await mkt.fetch_government(self._session, country_id)
            gov_names: dict[str, str] = {}
            if gov:
                gov_ids = [
                    gov.get(k) for k in
                    ("president", "vicePresident", "minOfDefense", "minOfForeignAffairs", "minOfEconomy")
                    if gov.get(k)
                ]
                if gov_ids:
                    gov_results = await asyncio.gather(*[get_user_lite(self._session, uid) for uid in gov_ids])
                    for uid, data in zip(gov_ids, gov_results):
                        gov_names[uid] = (data or {}).get("username", uid[:8] + "...")

            alliance_name = await resolve_alliance_name(self._session, country.get("allianceId"))

            tax_obj = country.get("taxes") or {}
            tax_income_pct = float(tax_obj.get("income") or 0)
            tax_market_pct = float(tax_obj.get("market") or 0)
            tax_self_pct = float(tax_obj.get("selfWork") or 0)

            tax_daily_24h = 0.0
            tax_core_24h = 0.0
            tax_noncore_24h = 0.0
            tax_from_ws = False
            try:
                now_ts = int(time.time())
                from_ts = now_ts - 86400
                ws_url = f"https://api.warerastats.io/country-tax-paid/{country_id}?from={from_ts}&to={now_ts}"
                async with self._session.get(ws_url, timeout=15) as r:
                    if r.status == 200:
                        ws_data = await r.json(content_type=None)
                        entries = ws_data.get("entries") or []
                        for entry in entries:
                            t = float(entry.get("taxes") or 0)
                            tax_daily_24h += t
                            if entry.get("core"):
                                tax_core_24h += t
                            else:
                                tax_noncore_24h += t
                        tax_from_ws = True
            except Exception as exc:
                log.warning(f"warerastats tax fetch: {exc}")

        rankings = country.get("rankings", {})
        wealth = rankings.get("countryWealth", {})
        dev_cur = float(country.get("currentDevelopment") or 0)
        dev_avg = float(country.get("averageDevelopment") or 0)
        dev_core = float(country.get("coreDevelopment") or 0)
        pop_active = int((rankings.get("countryActivePopulation") or {}).get("value") or 0)
        unrest = country.get("unrest", {})
        unrest_bar = unrest.get("bar", 0)
        unrest_max = unrest.get("barMax", 0)
        n_wars = len(country.get("warsWith", []) or [])
        n_allies = len(country.get("allies", []) or [])

        e = make_embed(f"🔍 Country Intel: {country_name}", discord.Color.blue())

        e.add_field(
            name="👥 Population & 📈 Development",
            value=(
                f"Active Population: `{pop_active}`\n"
                f"Dev: Current `{dev_cur:.2f}` · Avg `{dev_avg:.2f}` · Core `{dev_core:.2f}`\n"
                f"💰 Wealth: `{fmt_k(float(wealth.get('value') or 0))}` "
                f"(#{wealth.get('rank', '?')}, {wealth.get('tier', '?')})"
            ),
            inline=False,
        )

        e.add_field(
            name="💵 Taxes",
            value=(
                f"Income Tax: `{tax_income_pct}%`\n"
                f"Market Tax: `{tax_market_pct}%`\n"
                f"Self-Work Tax: `{tax_self_pct}%`"
            ),
            inline=True,
        )

        if top_items:
            item_lines = []
            for item_id, count in top_items:
                label = mkt.ITEM_LABELS.get(item_id, item_id)
                emoji = ITEM_EMOJI.get(label, "📦")
                item_lines.append(f"{emoji} {label}: `{count}` company")
            company_val = "\n".join(item_lines) + f"\n\n📦 Cache: {cache_age_str}"
        else:
            company_val = "ℹ️ Company index not available yet (next scan in ~3h)."
        e.add_field(name="🏭 Companies (top 3 item)", value=company_val, inline=True)

        if tax_from_ws and tax_daily_24h > 0:
            tax_val = (
                f"`{fmt_k(tax_daily_24h)}` gold/day (last 24h)\n"
                f"↳ Core region: `{fmt_k(tax_core_24h)}`\n"
                f"↳ Non-core region: `{fmt_k(tax_noncore_24h)}`\n"
                f"📊 Source: warerastats.io"
            )
        elif tax_from_ws and tax_daily_24h == 0:
            tax_val = "ℹ️ No tax recorded in the last 24 hours."
        else:
            tax_val = "⚠️ Failed to fetch tax data from warerastats.io."
        e.add_field(name="💰 Daily Tax (24h)", value=tax_val, inline=False)

        e.add_field(
            name="⚔️ Military",
            value=(
                f"At war with: `{n_wars}` countries\n"
                f"Alliance: {alliance_name} ({n_allies} allied countries)\n"
                f"Unrest: `{unrest_bar}/{unrest_max}`"
            ),
            inline=True,
        )

        if gov:
            gov_val = (
                f"President: {gov_names.get(gov.get('president'), '—')}\n"
                f"VP: {gov_names.get(gov.get('vicePresident'), '—')}\n"
                f"Min. Defense: {gov_names.get(gov.get('minOfDefense'), '—')}\n"
                f"Min. F.Affairs: {gov_names.get(gov.get('minOfForeignAffairs'), '—')}\n"
                f"Min. Economy: {gov_names.get(gov.get('minOfEconomy'), '—')}\n"
                f"Congress: `{len(gov.get('congressMembers', []) or [])}` members"
            )
        else:
            gov_val = "ℹ️ Government data not available."
        e.add_field(name="🏛️ Government", value=gov_val, inline=True)

        await ctx.send(embed=e)
