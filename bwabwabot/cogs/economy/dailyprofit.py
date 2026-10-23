"""
cogs/economy/dailyprofit.py  —  xdailyprofit (alias xdp)

Estimasi profit harian 1 pemain dari data riil: company, region, bonus
produksi per-region, wage sbg pekerja (live-verified worker.getWorkers,
bukan _get_wage_info). Beda dari xprofit (ideal per-AE) & xworkerprofit
(hire-pekerja ideal, wage flat asumsi).

Asumsi (selalu tampil di footer): usage 100% kontinu; AE 0/kosong -> lvl 1;
aksi entrepreneurship all-in ke 1 company (item yg diminta atau bonus
tertinggi lintas item, tie-break AE lalu company_id); item tak dikenali
ditandai, bukan didefault ke item lain; wage tak terdeteksi = 0.

Formula: stat = BASE_STATS + level*LEVEL_GAINS. PP kerja = (energy/10)*2.4
* production. PP manual/AE/worker dikali (1+bonus%/100), worker jg dikali
fidelity. Netting bahan antar company sebelum profit = income kerja +
revenue - payroll - biaya bahan.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands

import market as mkt
from services.spy.api_client import get_user_lite
from services.spy.search import find_player_exact
from services.territory import tax_store as store
from services.db.local import _local_connect

from services.economy.formatters import _fmt_money, _fmt_pct, _fmt_price
from .base import EconomyBase, _embed, AE_PP_PER_DAY, PRODUCTION_CHAIN, ITEM_EMOJI, log

# --- konstanta skill (referensi warera-eco-simulator, base+gain dicek sama
# persis dgn AE_PP_PER_DAY di bot per 22 Sept 2026) ---
BASE_STATS: dict[str, float] = {
    "entrepreneurship": 30,
    "energy": 30,
    "production": 10,
    "companies": 2,
    "management": 4,
}
LEVEL_GAINS: dict[str, float] = {
    "entrepreneurship": 5,
    "energy": 10,
    "production": 3,
    "companies": 1,
    "management": 2,
}
CYCLES_PER_DAY: float = 24 / 10  # 2.4

# default worker kalau data worker.getWorkers company itu gagal diambil
# (sama dgn default referensi & company-state.js)
DEFAULT_WORKER_ENERGY_PER_10H = 100.0
DEFAULT_WORKER_PRODUCTION_PER_ACTION = 31.0
DEFAULT_WORKER_WAGE = 0.135
DEFAULT_WORKER_FIDELITY_PCT = 0.0


def _effective_stat(level: int, skill: str) -> float:
    return BASE_STATS[skill] + (max(0, int(level or 0)) * LEVEL_GAINS[skill])


def _bonus_multiplier(bonus_pct: float) -> float:
    return 1 + (max(0.0, bonus_pct) / 100)


def _fidelity_multiplier(fidelity_pct: float) -> float:
    return 1 + (max(0.0, min(fidelity_pct, 10.0)) / 100)


class DailyProfitCommands(EconomyBase):

    # --- 1. resolve company + bonus produksi per company ---

    async def _resolve_companies_with_bonus(self, user_id: str) -> list[dict]:
        """Company milik user_id + bonus produksi per-region (bukan _get_bonus
        global). AE 0/kosong -> 1. Item tak dikenali ditandai known=False,
        tetap masuk list tapi exclude dari hitungan PP."""
        rows = await mkt.fetch_and_cache_user_companies(self._session, user_id)
        if not rows:
            return []

        countries, regions_obj = await mkt.get_bonus_raw_data(self._session, with_cache=True)
        countries_by_id = {c["_id"]: c for c in countries if c.get("_id")}

        party_ids = list({
            countries_by_id.get((regions_obj.get(r.get("region_id")) or {}).get("country"), {}).get("rulingParty")
            for r in rows
        } - {None})
        parties_by_id = await mkt._fetch_parties_batch(self._session, party_ids)

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

    # --- 2. pilih company target aksi entrepreneurship ---

    @staticmethod
    def _pick_entre_target(companies: list[dict], item_query: str | None) -> tuple[dict | None, str | None]:
        """(company_terpilih, error). Item yg diminta tapi tidak dipunya -> error."""
        known = [c for c in companies if c["known"]]

        if item_query:
            q = item_query.strip().lower().replace(" ", "")
            # 3-tahap sama seperti resolve_item() di base.py: exact -> startswith -> substring
            candidates = [c for c in known if c["item_label"].lower().replace(" ", "") == q]
            if not candidates:
                candidates = [c for c in known if c["item_label"].lower().replace(" ", "").startswith(q)]
            if not candidates:
                candidates = [c for c in known if q in c["item_label"].lower().replace(" ", "")]
            if not candidates:
                owned = sorted({c["item_label"] for c in known})
                owned_txt = ", ".join(owned) if owned else "(tidak ada company yang dikenali)"
                return None, f"⚠️ Pemain ini tidak punya company **{item_query}**. Company yang dimiliki: {owned_txt}"
        else:
            candidates = known
            if not candidates:
                return None, "⚠️ Tidak ada company dengan item yang dikenali bot untuk dialokasikan aksi entrepreneurship."

        candidates.sort(key=lambda c: (-c["bonus_pct"], -c["ae_level"], c["company_id"]))
        return candidates[0], None

    # --- 3. wage pemain (live-verified, BUKAN _get_wage_info yg salah asumsi buyerId) ---

    async def _resolve_own_wage(self, user_id: str) -> dict:
        """Wage tx terakhir -> buyer_id=employer -> live worker.getWorkers
        employer sampai match seller_id -> net = wage*(1-tax%/100).
        Not found -> net_wage=0.0 (bukan default 0.135 diam-diam)."""
        not_found = {"found": False, "net_wage": 0.0, "gross_wage": None,
                     "tax_pct": None, "employer_id": None, "company_id": None}

        tx = await self._get_last_wage_tx(user_id)
        if not tx or not tx.get("buyer_id"):
            return not_found

        employer_id = tx["buyer_id"]
        income_tax_rate = tx.get("income_tax_rate")

        try:
            employer_companies = await mkt.fetch_and_cache_user_companies(self._session, employer_id)
        except Exception:
            employer_companies = []

        for comp in employer_companies:
            company_id = comp.get("company_id")
            if not company_id:
                continue
            workers = await self._fetch_company_workers(company_id)
            for w in workers:
                if w.get("user_id") != user_id:
                    continue
                gross = w.get("wage")
                if gross is None or gross <= 0:
                    continue
                tax_pct = float(income_tax_rate) if income_tax_rate is not None else 0.0
                net = gross * (1 - tax_pct / 100)
                return {
                    "found": True,
                    "net_wage": net,
                    "gross_wage": gross,
                    "tax_pct": tax_pct,
                    "employer_id": employer_id,
                    "company_id": company_id,
                }

        return not_found

    async def _get_last_wage_tx(self, user_id: str) -> dict | None:
        """Wage tx terakhir milik user_id, dari territory_wage_events (app_db).
        Query mandiri di cog Economy sendiri (bukan numpang cog lain)."""
        return await asyncio.to_thread(self._query_last_wage_tx_sync, user_id)
    @staticmethod
    def _query_last_wage_tx_sync(seller_id: str) -> dict | None:
        row = store.get_seller_last_wage(seller_id)
        if not row:
            return None
        created_at = row.get("created_at")
        return {
            "buyer_id": row.get("buyer_id"),
            "company_id": row.get("company_id"),
            "income_tax_rate": float(row["income_tax_rate"]) if row.get("income_tax_rate") is not None else None,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        }

    # --- 4. worker per company milik pemain sendiri ---

    async def _fetch_company_workers(self, company_id: str) -> list[dict]:
        """Live worker.getWorkers untuk 1 company."""
        try:
            url = f"{mkt.WORKERS_URL}?input={mkt._encode({'companyId': company_id})}"
            resp = await mkt._get_json_with_retry(
                self._session, url, headers=mkt._auth_headers(), timeout=15,
            )
            data = resp["result"]["data"]
        except Exception:
            return []

        raw_workers = data.get("workers", []) if isinstance(data, dict) else []
        return [
            {
                "user_id": w.get("user"),
                "employer_id": w.get("employer"),
                "wage": w.get("wage"),
                "fidelity": w.get("fidelity") or 0,
                "joined_at": w.get("joinedAt"),
            }
            for w in raw_workers
        ]

    # --- 5. hitung PP & profit ---

    async def _calculate(
        self, alloc: dict, companies: list[dict], target: dict, own_net_wage: float,
    ) -> dict:
        stats = {k: _effective_stat(alloc.get(k, 0), k) for k in BASE_STATS}

        work_actions_per_day = (stats["energy"] / 10) * CYCLES_PER_DAY
        entre_actions_per_day = (stats["entrepreneurship"] / 10) * CYCLES_PER_DAY

        work_pp_day = work_actions_per_day * stats["production"]
        work_income_day = work_pp_day * own_net_wage

        management_remaining = stats["management"]

        pp_budget_by_item: dict[str, float] = {}
        payroll_cost_day = 0.0
        company_cards = []

        for comp in companies:
            if not comp["known"]:
                company_cards.append({**comp, "skipped": True, "reason": "item tidak dikenali"})
                continue

            label = comp["item_label"]
            mult = _bonus_multiplier(comp["bonus_pct"])

            manual_pp = 0.0
            if target is not None and comp["company_id"] == target["company_id"]:
                manual_pp = entre_actions_per_day * stats["production"] * mult

            ae_pp = AE_PP_PER_DAY.get(comp["ae_level"], 0) * mult

            worker_pp = 0.0
            workers_detected = 0
            worker_source = "none"
            if comp["worker_count"] > 0:
                if management_remaining > 0:
                    workers = await self._fetch_company_workers(comp["company_id"])
                    worker_source = "live" if workers else "estimasi"
                    if not workers:
                        workers = [
                            {"user_id": None, "wage": DEFAULT_WORKER_WAGE,
                             "fidelity": DEFAULT_WORKER_FIDELITY_PCT,
                             "energy_per_10h": DEFAULT_WORKER_ENERGY_PER_10H,
                             "production_per_action": DEFAULT_WORKER_PRODUCTION_PER_ACTION}
                            for _ in range(comp["worker_count"])
                        ]
                    active = workers[:max(0, int(management_remaining))]
                    management_remaining -= len(active)
                    workers_detected = len(active)
                    for w in active:
                        e10h = w.get("energy_per_10h", DEFAULT_WORKER_ENERGY_PER_10H)
                        ppa = w.get("production_per_action", DEFAULT_WORKER_PRODUCTION_PER_ACTION)
                        fid = w.get("fidelity", DEFAULT_WORKER_FIDELITY_PCT) or 0
                        wage = w.get("wage") or DEFAULT_WORKER_WAGE
                        actions = (e10h / 10) * CYCLES_PER_DAY
                        raw_pp = actions * ppa
                        worker_pp += raw_pp * mult * _fidelity_multiplier(fid)
                        payroll_cost_day += raw_pp * wage
                else:
                    worker_source = "management_penuh"

            pp_budget = manual_pp + ae_pp + worker_pp
            pp_budget_by_item[label] = pp_budget_by_item.get(label, 0.0) + pp_budget

            company_cards.append({
                **comp, "skipped": False, "manual_pp": manual_pp,
                "ae_pp": ae_pp, "worker_pp": worker_pp, "pp_budget": pp_budget,
                "workers_detected": workers_detected, "worker_source": worker_source,
            })

        # netting bahan lintas company (pola _calculate_company_income)
        order = sorted(PRODUCTION_CHAIN.items(), key=lambda kv: 0 if kv[1]["input"] is None else 1)
        inventory: dict[str, float] = {}
        produced: dict[str, float] = {}
        bought_cost_by_item: dict[str, float] = {}

        for label, chain in order:
            budget = pp_budget_by_item.get(label, 0.0)
            if budget <= 0 or chain["pp"] <= 0:
                continue
            units = budget / chain["pp"]
            if chain["input"]:
                input_label, input_qty = chain["input"]
                required = units * input_qty
                available = max(0.0, inventory.get(input_label, 0.0))
                from_stock = min(available, required)
                missing = max(0.0, required - from_stock)
                inventory[input_label] = inventory.get(input_label, 0.0) - from_stock
                price = self._price_cache.get(input_label, 0.0)
                bought_cost_by_item[label] = bought_cost_by_item.get(label, 0.0) + missing * price
            inventory[label] = inventory.get(label, 0.0) + units
            produced[label] = produced.get(label, 0.0) + units

        revenue_day = 0.0
        for label, qty in inventory.items():
            if qty > 0:
                revenue_day += qty * self._price_cache.get(label, 0.0)
        ingredient_cost_day = sum(bought_cost_by_item.values())

        net_profit_day = work_income_day + revenue_day - payroll_cost_day - ingredient_cost_day

        return {
            "stats": stats,
            "work_actions_per_day": work_actions_per_day,
            "entre_actions_per_day": entre_actions_per_day,
            "work_pp_day": work_pp_day,
            "work_income_day": work_income_day,
            "payroll_cost_day": payroll_cost_day,
            "revenue_day": revenue_day,
            "ingredient_cost_day": ingredient_cost_day,
            "net_profit_day": net_profit_day,
            "company_cards": company_cards,
            "produced": produced,
        }

    # --- command ---

    @commands.command(name="dailyprofit", aliases=["dp"])
    async def cmd_dailyprofit(self, ctx: commands.Context, username: str, *, item: str | None = None) -> None:
        if not self._price_cache:
            await ctx.send("⏳ Data not ready yet.")
            return

        spy_cog = self.bot.get_cog("SpyCog")
        if spy_cog is None:
            await ctx.send("❌ Spy module belum siap.")
            return

        async with ctx.typing():
            player, suggestions = await find_player_exact(self._session, username)
            if player is None:
                sug = f" Mungkin maksud kamu: {', '.join(suggestions)}" if suggestions else ""
                await ctx.send(f"❌ Pemain **{username}** tidak ditemukan.{sug}")
                return

            user_id = player.get("_id")
            user_lite = await get_user_lite(self._session, user_id)
            if user_lite is None:
                await ctx.send("❌ Gagal mengambil data skill pemain.")
                return

            skills = user_lite.get("skills", {})
            alloc = {k: int((skills.get(k, {}) or {}).get("level") or 0) for k in BASE_STATS}

            companies = await self._resolve_companies_with_bonus(user_id)
            target, err = self._pick_entre_target(companies, item)
            if err:
                await ctx.send(err)
                return

            wage_info = await self._resolve_own_wage(user_id)

            result = await self._calculate(alloc, companies, target, wage_info["net_wage"])

        e = _embed(f"📈 Daily Profit Estimate — {player.get('username', username)}", discord.Color.blurple())

        lines = [
            f"**Skill (level → stat):** "
            + " | ".join(f"{k}: {alloc[k]}→{result['stats'][k]:.0f}" for k in BASE_STATS),
            "",
            f"**Aksi kerja/hari:** {result['work_actions_per_day']:.2f} "
            f"(PP: {result['work_pp_day']:.1f})",
        ]
        if wage_info["found"]:
            lines.append(
                f"**Wage (net):** {_fmt_price(wage_info['net_wage'])}/pp "
                f"(gross {_fmt_price(wage_info['gross_wage'])}, pajak {_fmt_pct(wage_info['tax_pct'])}%)"
            )
        else:
            lines.append("**Wage:** ⚠️ tidak terdeteksi (dianggap 0 di total)")

        lines.append("")
        target_id = target["company_id"] if target else None
        for c in result["company_cards"]:
            emoji = ITEM_EMOJI.get(c.get("item_label"), "•")
            tag = " 🎯" if c["company_id"] == target_id else ""
            if c.get("skipped"):
                lines.append(f"{emoji} {c['name'] or c['company_id']} — ⚠️ item tidak dikenali ({c['raw_item_code']})")
                continue
            parts = []
            if c["manual_pp"] > 0:
                parts.append(f"manual {c['manual_pp']:.0f}")
            parts.append(f"AE {c['ae_pp']:.0f}")
            if c["worker_count"] > 0:
                parts.append(f"worker {c['worker_pp']:.0f} ({c['workers_detected']}/{c['worker_count']} {c['worker_source']})")
            lines.append(
                f"{emoji} **{c['item_label']}**{tag} AE{c['ae_level']} "
                f"(+{_fmt_pct(c['bonus_pct'])}%) — PP: {c['pp_budget']:.1f}/hari ({' + '.join(parts)})"
            )

        lines.append("")
        lines.append(f"**Revenue jual:** +{_fmt_money(result['revenue_day'])}")
        lines.append(f"**Biaya bahan:** -{_fmt_money(result['ingredient_cost_day'])}")
        lines.append(f"**Payroll:** -{_fmt_money(result['payroll_cost_day'])}")
        lines.append(f"**Profit/hari:** **{_fmt_money(result['net_profit_day'])}**")

        e.description = "\n".join(lines)
        e.set_footer(
            text=(
                "⚠️ Estimasi, bukan angka pasti. Asumsi: usage 100% (main nonstop), "
                "aksi entrepreneurship all-in ke 1 company (🎯) dgn bonus tertinggi. "
                "Wage tidak terdeteksi dianggap 0."
            )
        )
        await ctx.send(embed=e)
