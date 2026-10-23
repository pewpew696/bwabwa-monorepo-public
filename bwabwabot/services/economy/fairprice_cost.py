# services/economy/fairprice_cost.py — kalkulasi murni cost engine fairprice (PP value + production cost)

from __future__ import annotations

from typing import Callable

from .constants import PRODUCTION_CHAIN


def fp_pp_value(price_cache: dict[str, float], exclude: str | None = None) -> float:
    """Harga dasar 1 PP = rata-rata harga tier-1 (Iron/Wood/Grain/Limestone)."""
    tier_1_items = ["Iron", "Wood", "Grain", "Limestone"]
    total_price = 0.0
    count = 0

    for item in tier_1_items:
        if exclude is not None and item == exclude:
            continue
        price = price_cache.get(item)
        if price and price > 0:
            total_price += price
            count += 1

    if count == 0:
        return 0.0

    return total_price / count


def fp_production_cost(
    price_cache: dict[str, float],
    item: str,
    pp_value: float,
    bonus_pct: float,
    bonus_source: str,
) -> dict | None:
    chain = PRODUCTION_CHAIN.get(item)
    if chain is None:
        return None

    # median bonus, bukan max -- max bikin cost selalu optimis
    output_mult = 1 + bonus_pct / 100

    input_cost = 0.0
    input_ok   = True
    if chain["input"] is not None:
        in_name, in_qty = chain["input"]
        in_price = price_cache.get(in_name)
        if in_price is None:
            input_ok = False
        else:
            input_cost = in_qty * in_price

    pp_cost = pp_value * chain["pp"]
    production_cost = (input_cost + pp_cost) / output_mult if output_mult > 0 else None

    return {
        "production_cost": production_cost,
        "input_cost":      input_cost,
        "pp_cost":         pp_cost,
        "output_mult":     output_mult,
        "bonus_pct":       bonus_pct,
        "bonus_source":    bonus_source,
        "input_ok":        input_ok,
    }


def fp_compute_cost_engine(
    price_cache: dict[str, float],
    item: str,
    is_producible: bool,
    get_median_bonus: Callable[[str], tuple[float, str]],
    get_bonus: Callable[[str], tuple[float, str]],
) -> dict | None:
    """Cost engine lengkap: pp_value + cost_info + bonus + break_even.

    Return None kalau:
    - producible & pp_value <= 0 (tier-1 harga kosong)
    - producible & cost_info None / production_cost None / input_ok False
    Non-producible selalu return dict dengan nilai default (None / 0.0).
    """
    if not is_producible:
        return {
            "pp_value":       0.0,
            "cost_info":      None,
            "bonus_best_pct": None,
            "production_cost": None,
            "break_even":     None,
        }

    pp_value = fp_pp_value(price_cache, exclude=item)
    if pp_value <= 0:
        return None

    bonus_pct, bonus_source = get_median_bonus(item)
    cost_info = fp_production_cost(price_cache, item, pp_value, bonus_pct, bonus_source)
    if cost_info is None or cost_info["production_cost"] is None or not cost_info["input_ok"]:
        return None

    bonus_best_pct, _bonus_best_source = get_bonus(item)
    production_cost = cost_info["production_cost"]

    return {
        "pp_value":       pp_value,
        "cost_info":      cost_info,
        "bonus_best_pct": bonus_best_pct,
        "production_cost": production_cost,
        "break_even":     production_cost,
    }

