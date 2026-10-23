# simulator/engine.py — facade modul simulator

import logging

from simulator.economy_quick import (
    _calculate_company_income,
    _calculate_equipment_wear_cost,
    _craft_cost,
    calculate_daily_projection,
    quick_simulate,
    round_sim,
)
from simulator.session_hits import (
    calculate_debuff_maintenance_hits,
    calculate_max_hits,
    plan_hit_budget,
    plan_hit_budget_no_pill,
    simulate_session,
)
from simulator.stats_combat import (
    calculate_base_stats,
    execute_combat_action,
)

log = logging.getLogger("WarEraBot.engine")

__all__ = [
    "calculate_base_stats",
    "execute_combat_action",
    "simulate_session",
    "calculate_max_hits",
    "calculate_debuff_maintenance_hits",
    "plan_hit_budget",
    "plan_hit_budget_no_pill",
    "_craft_cost",
    "_calculate_equipment_wear_cost",
    "_calculate_company_income",
    "quick_simulate",
    "round_sim",
    "calculate_daily_projection",
]
