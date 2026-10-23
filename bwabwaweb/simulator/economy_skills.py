# economy_skills.py
"""Skill ekonomi: work income & company income (pure math).

Port pure-math dari cogs/economy/dailyprofit.py::_calculate — TANPA yang
Discord/API-coupled (resolve companies live, fetch workers live, embeds,
commands). Simplified: tanpa worker/payroll (skill management tidak dipakai).

Rumus (dari dailyprofit.py, dicek 2026-10-09):
- stat = BASE_STATS + level * LEVEL_GAINS
- work_actions/hari = (energy_eff / 10) * 2.4
- work_pp = work_actions * production_eff
- work_income = work_pp * wage_net (upah bersih per PP sbg pekerja, input user)
- entre_actions/hari = (entrepreneurship_eff / 10) * 2.4, all-in ke SATU
  company dgn bonus_pct tertinggi:
  manual_pp = entre_actions * production_eff * (1 + bonus/100)
- per company: ae_pp = AE_PP_PER_DAY[ae_level] * (1 + bonus/100)
- netting bahan antar company: raw dulu (tanpa input), lalu olahan;
  inventory, produced, bought_cost_by_item.

Tanpa discord/fastapi. Aman diimport dari mana saja.
"""
from simulator.constants import AE_PP_PER_DAY, PRODUCTION_CHAIN

# Konstanta skill ekonomi (port dailyprofit.py; referensi warera-eco-simulator).
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

# Skill yang masuk rumus eco di sini (beda dari services/spy/constants.py::
# ECO_SKILLS yang berisi 5 skill ekonomi; management & companies skill
# ditangani terpisah — Simplified tanpa worker).
ECO_FORMULA_SKILLS = ("energy", "production", "entrepreneurship")


def effective_stat(level: int, skill: str) -> float:
    """stat efektif = base + level * gain (port dailyprofit._effective_stat)."""
    if skill not in BASE_STATS:
        raise ValueError(f"eco skill tidak dikenal: {skill}")
    return BASE_STATS[skill] + (max(0, int(level or 0)) * LEVEL_GAINS[skill])


def calculate_eco_income(
    eco_levels: dict | None,
    companies: list[dict] | None,
    wage_net: float,
    market: dict | None,
) -> dict:
    """Hitung work income + company income harian (pure).

    Args:
        eco_levels: {"energy": lv, "production": lv, "entrepreneurship": lv} (0-10).
        companies: [{"ae_level": 1-7, "production_target": item,
                     "bonus_pct": float}] — production_target WAJIB ada di
            PRODUCTION_CHAIN, kalau tidak ValueError.
        wage_net: upah bersih per PP sebagai pekerja (>= 0).
        market: {item: harga} untuk revenue & biaya bahan.

    Returns: {"work_income_day", "revenue_day", "ingredient_cost_day",
        "company_net", "company_cards", "entre_target_idx"}.
    """
    eco_levels = eco_levels or {}
    market = market or {}
    wage = max(0.0, float(wage_net or 0.0))

    energy_eff = effective_stat(eco_levels.get("energy", 0), "energy")
    prod_eff = effective_stat(eco_levels.get("production", 0), "production")
    entre_eff = effective_stat(eco_levels.get("entrepreneurship", 0), "entrepreneurship")

    # Kerja sebagai pekerja: aksi/hari dari energy, PP dari production.
    work_actions = (energy_eff / 10) * CYCLES_PER_DAY
    work_pp = work_actions * prod_eff
    work_income_day = work_pp * wage

    # Validasi company (fail fast, sebelum hitung apa pun).
    valid: list[dict] = []
    for c in companies or []:
        target = c.get("production_target")
        if target not in PRODUCTION_CHAIN:
            raise ValueError(f"production_target tidak dikenal: {target}")
        valid.append({
            "ae_level": int(c.get("ae_level", 1) or 1),
            "production_target": target,
            "bonus_pct": max(0.0, float(c.get("bonus_pct", 0) or 0.0)),
        })

    # Entrepreneurship all-in ke SATU company bonus tertinggi
    # (port _pick_entre_target tanpa item_query: bonus desc, ae desc).
    target_idx: int | None = None
    if valid:
        target_idx = max(
            range(len(valid)),
            key=lambda i: (valid[i]["bonus_pct"], valid[i]["ae_level"]),
        )
    entre_actions = (entre_eff / 10) * CYCLES_PER_DAY

    pp_budget_by_item: dict[str, float] = {}
    cards: list[dict] = []
    for i, comp in enumerate(valid):
        mult = 1 + comp["bonus_pct"] / 100
        manual_pp = entre_actions * prod_eff * mult if i == target_idx else 0.0
        ae_pp = AE_PP_PER_DAY.get(comp["ae_level"], 0) * mult
        pp_budget = manual_pp + ae_pp
        item = comp["production_target"]
        pp_budget_by_item[item] = pp_budget_by_item.get(item, 0.0) + pp_budget
        cards.append({
            "ae_level": comp["ae_level"],
            "production_target": item,
            "bonus_pct": comp["bonus_pct"],
            "manual_pp": round(manual_pp, 2),
            "ae_pp": round(ae_pp, 2),
            "pp_budget": round(pp_budget, 2),
            "is_entre_target": i == target_idx,
        })

    # Netting bahan lintas company (port dailyprofit: raw dulu).
    order = sorted(
        PRODUCTION_CHAIN.items(),
        key=lambda kv: 0 if kv[1]["input"] is None else 1,
    )
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
            bought_cost_by_item[label] = (
                bought_cost_by_item.get(label, 0.0)
                + missing * market.get(input_label, 0.0)
            )
        inventory[label] = inventory.get(label, 0.0) + units
        produced[label] = produced.get(label, 0.0) + units

    revenue_day = sum(
        qty * market.get(label, 0.0)
        for label, qty in inventory.items() if qty > 0
    )
    ingredient_cost_day = sum(bought_cost_by_item.values())
    company_net = revenue_day - ingredient_cost_day

    return {
        "work_income_day": work_income_day,
        "revenue_day": revenue_day,
        "ingredient_cost_day": ingredient_cost_day,
        "company_net": company_net,
        "company_cards": cards,
        "entre_target_idx": target_idx,
    }
