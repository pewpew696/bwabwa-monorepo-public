# companies_service.py
"""Logika Company Explorer: ringkasan per item + drilldown AE & negara.

Semua data dari DB (bot yang fetch); bonus produksi dihitung dari
api_cache countries/regions_obj — TANPA fetch API WarEra.
"""
from __future__ import annotations

from datetime import datetime, timezone

from services.economy.bonus import _country_bonus_pct, _deposit_bonus_pct
from services.economy.items import _item_id_from_api_key

from webapp.queries import queries_companies, queries_fiscal, queries_territory


class CompaniesService:
    def __init__(self, companies_queries, fiscal_queries, territory_queries) -> None:
        self._q = companies_queries
        self._fq = fiscal_queries
        self._tq = territory_queries

    def _label_for(self, item_code: str) -> str:
        try:
            import market
            return market.ITEM_LABELS.get(item_code, item_code)
        except Exception:
            return item_code

    def get_item_summary(self) -> list[dict]:
        rows = self._q.get_item_summary()
        out = []
        for row in rows:
            code = row.get("item_code") or ""
            out.append({
                "item_code": code,
                "item_label": self._label_for(code),
                "companies": int(row.get("companies") or 0),
                "total_workers": int(row.get("total_workers") or 0),
                "with_ae": int(row.get("with_ae") or 0),
                "last_updated": row.get("last_updated"),
            })
        return out

    def _bonus_pct_for(self, country: dict | None, region: dict | None, item_id: str) -> float:
        """Port ringan bonus.py: country + deposit bonus.

        TODO(party): bonus party (industrialism) belum dihitung di fase 1 —
        butuh data party yang tidak ada di api_cache. Party dianggap netral (None).
        """
        if not country:
            return 0.0
        total = _country_bonus_pct(country, item_id, None) + _deposit_bonus_pct(
            region, item_id, None, datetime.now(timezone.utc)
        )
        return round(total, 6)

    def get_item_breakdown(self, item_code: str) -> dict:
        item_id = _item_id_from_api_key(item_code) or item_code

        per_ae = [
            {
                "ae_level": int(r.get("ae_level") or 0),
                "companies": int(r.get("companies") or 0),
                "total_workers": int(r.get("total_workers") or 0),
            }
            for r in self._q.get_item_ae_breakdown(item_code)
        ]

        # Mapping region -> negara dari api_cache (sekali fetch di service layer).
        regions_obj = self._q.get_region_country_map()
        names = self._fq.get_country_names()

        # Agregasi per negara di Python (bukan JOIN SQL ke JSON).
        agg: dict[str, dict] = {}
        for row in self._q.get_item_country_rows(item_code):
            region_id = row.get("region_id")
            region = regions_obj.get(region_id) or {}
            country_id = region.get("country") or "_"
            bucket = agg.setdefault(
                country_id, {"companies": 0, "total_workers": 0, "regions": []}
            )
            bucket["companies"] += int(row.get("companies") or 0)
            bucket["total_workers"] += int(row.get("total_workers") or 0)
            bucket["regions"].append(region_id)

        # Bonus per negara untuk item ini (country + deposit, party netral).
        countries_by_id = {}
        try:
            countries_by_id = {
                c.get("_id"): c for c in self._tq.get_countries() if c.get("_id")
            }
        except Exception:
            countries_by_id = {}

        per_country = []
        for country_id, bucket in agg.items():
            country = countries_by_id.get(country_id)
            if country:
                # Deposit bonus butuh region; pakai region pertama negara itu
                # (deposit umumnya per-region, kita ambil contoh representatif).
                first_region = None
                for rid in bucket["regions"]:
                    first_region = regions_obj.get(rid)
                    if first_region:
                        break
                bonus = self._bonus_pct_for(country, first_region, item_id)
            else:
                bonus = 0.0
            per_country.append({
                "country_id": country_id,
                "country_name": names.get(country_id, country_id),
                "companies": bucket["companies"],
                "total_workers": bucket["total_workers"],
                "region_count": len(bucket["regions"]),
                "bonus_pct": bonus,
            })
        per_country.sort(key=lambda r: (-r["companies"], r["country_name"]))

        return {
            "item_code": item_code,
            "item_label": self._label_for(item_code),
            "per_ae": per_ae,
            "per_country": per_country,
        }
