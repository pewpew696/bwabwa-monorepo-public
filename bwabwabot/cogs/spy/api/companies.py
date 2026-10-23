"""cogs/spy/api/companies.py — data company milik player: owned companies,
estimasi nilai produksi AE, status slot AE. Dipecah dari api.py (dulu 1 file
1175 baris)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..constants import COMPANY_PRODUCTION_MAX_ROWS

log = logging.getLogger("WarEraBot.spy")


class CompanyDataMixin:
    """Mixin — expects self.bot dari class final
    (SpyCog di __init__.py, lewat CompanyScanMixin)."""

    # --- companies owned / AE slot status ---
    async def _estimate_company_production_value(
        self, company_rows: list[dict], since_dt: datetime,
    ) -> tuple[float, dict[str, float]]:
        """
        Estimasi upper-bound nilai gold dari produksi company murni-AE
        (worker_count == 0) milik 1 player sejak `since_dt`, dipakai buat
        rekonsiliasi wealth (xspy check) supaya item yang numpuk di
        inventory (belum lewat ledger gold) tetap terhitung.

        Company dengan worker_count > 0 dilewati di sini karena nilainya
        sudah tercover lewat ledger `wage` di rekonsiliasi gold biasa --
        kalau ikut dihitung di sini akan dobel.

        Formula per company:
          pp_per_day    = economy.AE_PP_PER_DAY[ae_level] (0 kalau ae_level
                          tidak ada di tabel / company tidak pakai AE)
          bonus_pct     = EconomyCog._get_bonus(label) -- opsi 1 (cross-cog
                          call) dengan null-check kalau EconomyCog belum load
          units_per_day = (pp_per_day * (1+bonus_pct/100)) / chain["pp"]
                          (chain dari economy.PRODUCTION_CHAIN)
          value_per_day = units_per_day * harga_market (EconomyCog._price_cache)

        NOTE: ini upper-bound kasar (asumsi AE jalan penuh, tanpa idle time).
        Kalau harga item / chain PP tidak ditemukan, company itu dilewati
        (tidak dianggap 0, tapi tidak dihitung sama sekali) supaya nggak
        salah under-estimate.

        Return: (total_value_upper_bound, breakdown {item_label: value})
        """
        import cogs.economy as eco
        import market as mkt

        econ_cog = self.bot.get_cog("Economy")

        days_elapsed = max(0.01, (datetime.now(timezone.utc) - since_dt).total_seconds() / 86400)

        total_value = 0.0
        breakdown: dict[str, float] = {}

        for row in company_rows[:COMPANY_PRODUCTION_MAX_ROWS]:
            if int(row.get("worker_count") or 0) > 0:
                continue

            ae_level = int(row.get("ae_level") or 0)
            pp_per_day = eco.AE_PP_PER_DAY.get(ae_level, 0)
            if pp_per_day <= 0:
                continue

            raw_code = row.get("item_code") or ""
            item_id = mkt.API_KEY_TO_ITEM_ID.get(raw_code, raw_code)
            label = mkt.ITEM_LABELS.get(item_id, item_id)

            chain = eco.PRODUCTION_CHAIN.get(label)
            if not chain or not chain.get("pp"):
                continue

            bonus_pct = 0.0
            if econ_cog is not None:
                try:
                    bonus_pct, _source = econ_cog._get_bonus(label)
                except Exception as exc:
                    log.warning(f"_estimate_company_production_value _get_bonus({label}): {exc}")

            price = econ_cog._price_cache.get(label) if econ_cog is not None else None
            if price is None:
                continue

            adj_pp_per_day = pp_per_day * (1 + bonus_pct / 100)
            units_per_day = adj_pp_per_day / chain["pp"]
            value_per_day = units_per_day * price
            value_period = value_per_day * days_elapsed

            total_value += value_period
            breakdown[label] = breakdown.get(label, 0.0) + value_period

        return total_value, breakdown

    def _ae_slot_status(self, company_rows: list[dict], ae_slot_max: int) -> tuple[int, int, int]:
        """
        Bandingkan jumlah company idle (worker_count == 0) terhadap slot AE
        maksimal (skills.companies.value). Return:
          (idle_count, active_via_ae, truly_idle)
        """
        idle_count = sum(1 for r in company_rows if int(r.get("worker_count") or 0) == 0)
        active_via_ae = min(idle_count, ae_slot_max)
        truly_idle = max(0, idle_count - ae_slot_max)
        return idle_count, active_via_ae, truly_idle
