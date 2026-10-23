# builder_service.py
"""Build Optimizer: Monte Carlo RNG beneran (mode Balance, Simplified).

DILARANG pakai quick_simulate (expected value) di jalur ini — keputusan owner
2026-10-09: hasil harus benar-benar teruji. Tiap build dijalankan
MONTE_CARLO_RUNS x simulate_session() per fase, lalu diambil mean + std.

Tanpa fastapi. Pure compute + compare store in-memory (single worker uvicorn).
"""
import statistics
import threading

from simulator.constants import (
    FOOD_ITEMS,
    SCRAP_RECOVERY_RATIO,
    SKILL_MAX_LEVEL,
    SKILLS,
)
from simulator.economy_skills import calculate_eco_income
from simulator.session_hits import (
    plan_hit_budget,
    plan_hit_budget_no_pill,
    simulate_session,
)
from simulator.stats_combat import calculate_base_stats
from webapp.web_services.builder_models import (
    BuildConfig,
    BuildResult,
    Mode,
    build_advanced_equipment,
    resolve_market_prices,
)
from webapp.web_services.simulator_service import (
    DEFAULT_DEBUFF_WEAPON,
    build_equipment_from_rarity,
)

# Monte Carlo: simulate_session dijalankan N kali per fase per build.
# ~6 us/hit -> 100 x 300 hits ~= 0.2 detik per build (benchmark 2026-10-09).
# Tetap via asyncio.to_thread di route (berat untuk event loop).
MONTE_CARLO_RUNS = 100

COMPARE_LIMIT = 10
_MAX_BUCKETS = 2000


def _engine_equipment(config: BuildConfig) -> dict:
    """BuildConfig -> format engine {slot: {stats, durability, [rarity|value]}}.

    Simplified: rarity -> midpoint stats (jalur lama). Advanced: stat exact
    user (slot tanpa stat > 0 dilewati).
    """
    if config.detail == "advanced":
        return build_advanced_equipment(config)
    raw = build_equipment_from_rarity(dict(config.equipment))
    return {
        slot: {"rarity": d["rarity"], "durability": 100,
               "stats": {k: v for k, v in d.items() if k != "rarity"}}
        for slot, d in raw.items()
    }


_compare_lock = threading.Lock()
_compare_buckets: dict[str, list[dict]] = {}
# Pin skills: {session_key}:pins -> {skill: level}. Lintas mode (TIDAK
# per-mode) — pin = preferensi sesi, fondasi untuk optimizer nanti.
_pin_buckets: dict[str, dict[str, int]] = {}


class BuilderService:
    """Hitung satu build (Monte Carlo) + kelola tabel banding per sesi."""

    def _run_phase(self, stats: dict, battle_config: dict, economy_config: dict,
                   num_hits: int, equipment: dict, regen_pool, hunger_budget,
                   starts: list | None, runs: int) -> list[dict]:
        """N x simulate_session satu fase; starts = ending_hp fase lalu per run."""
        out = []
        for i in range(runs):
            out.append(simulate_session(
                stats, battle_config, economy_config, num_hits,
                equipment=equipment, regen_pool=regen_pool,
                hunger_budget=hunger_budget,
                starting_hp=starts[i] if starts is not None else None,
            ))
        return out

    def calculate_build(
        self, config: BuildConfig, market_prices: dict | None
    ) -> BuildResult:
        # Semua mode jalan (Balance/Farmer/Glass Cannon) — bedanya hanya
        # metrik ranking di compare store (lihat _sort_entries).
        # Harga efektif = DB + override user (override hanya di Advanced).
        # Anti-hardcode: item yang dibutuhkan harus ada di salah satunya.
        market, overrides_used = resolve_market_prices(config, market_prices)
        skills = dict(config.skills)

        equip_full = _engine_equipment(config)
        stats_full = calculate_base_stats(skills, equip_full, config.char_level)
        food_heal_pct = (
            0.0 if config.food_type == "none" else FOOD_ITEMS[config.food_type]["heal_pct"]
        )
        base_bc = {
            "ammo_tier": config.ammo_tier,
            "rank_bonus_pct": config.rank_bonus_pct,
            "battle_bonus_pct": config.battle_bonus_pct,
        }
        economy = {"market_prices": market, "food_type": config.food_type}
        runs = MONTE_CARLO_RUNS

        # Spec satu fase: (stats, bc, econ, hits, equip, regen, hunger, chain).
        # chain=True -> starting_hp = ending_hp fase sebelumnya (per run).
        # Struktur fase cermin run_cycle_impl (simulator_service).
        specs: list[tuple] = []
        pill_cost = 0.0
        if config.pill == "buff":
            stats_debuff = calculate_base_stats(
                skills, DEFAULT_DEBUFF_WEAPON, config.char_level
            )
            plan = plan_hit_budget(stats_full, stats_debuff, food_heal_pct, config.window)
            buff = plan["phases"]["buff"]
            specs.append((stats_full, dict(base_bc, pill_state="buff"), economy,
                          buff["max_hits"], equip_full, buff["regen_pool"],
                          buff["hunger_budget"], False))
            if "debuff" in plan["phases"]:
                deb = plan["phases"]["debuff"]
                specs.append((stats_debuff,
                              dict(base_bc, ammo_tier="none", pill_state="debuff"),
                              {"market_prices": market, "food_type": "none"},
                              deb["maintenance_hits"], DEFAULT_DEBUFF_WEAPON,
                              deb["regen_at_risk"], 0, True))
            if "none" in plan["phases"]:
                non = plan["phases"]["none"]
                specs.append((stats_full, dict(base_bc, pill_state="none"), economy,
                              non["max_hits"], equip_full, non["regen_pool"],
                              non["hunger_budget"], True))
            # Biaya pill di service layer, pola simulator_service.py.
            pill_cost = float(market.get("Pill", 0) or 0)
        else:
            plan = plan_hit_budget_no_pill(stats_full, food_heal_pct, config.window)
            non = plan["phases"]["none"]
            specs.append((stats_full, dict(base_bc, pill_state="none"), economy,
                          non["max_hits"], equip_full, non["regen_pool"],
                          non["hunger_budget"], False))

        # Total per run lintas fase, lalu mean + std antar run.
        totals = [{"damage": 0.0, "wear": 0.0, "ammo": 0.0,
                   "food": 0.0, "cases": 0.0, "hits": 0} for _ in range(runs)]
        prev_ending: list | None = None
        for stats, bc, econ, hits, equip, regen, hunger, chain in specs:
            phase_runs = self._run_phase(
                stats, bc, econ, hits, equip, regen, hunger,
                prev_ending if chain else None, runs)
            for i, res in enumerate(phase_runs):
                t = totals[i]
                t["damage"] += res["total_damage"]
                t["wear"] += res["equipment_wear_cost"]
                t["ammo"] += res["ammo_cost"]
                t["food"] += res["food_cost"]
                t["cases"] += res["loot_income"]
                t["hits"] += res["hits_completed"]
            prev_ending = [r["ending_hp"] for r in phase_runs]

        damages = [t["damage"] for t in totals]
        mean_damage = statistics.fmean(damages)
        std_damage = statistics.stdev(damages) if runs > 1 else 0.0
        mean_wear = statistics.fmean(t["wear"] for t in totals)
        mean_ammo = statistics.fmean(t["ammo"] for t in totals)
        mean_food = statistics.fmean(t["food"] for t in totals)
        mean_cases = statistics.fmean(t["cases"] for t in totals)
        mean_hits = statistics.fmean(t["hits"] for t in totals)

        # Battle loot: DI-SKIP (keputusan owner 2026-10-09) — mekanik game
        # belum bisa dipetakan, jadi tidak dimasukkan sampai jelas.
        # Konstanta/model Fase 1 tetap ada di economy_quick (riset), tapi
        # tidak dipakai di jalur builder.
        loot_income = 0.0
        scrap_income = SCRAP_RECOVERY_RATIO * mean_wear

        # Economy: work & company income (port cogs/economy/dailyprofit.py).
        eco = calculate_eco_income(
            config.eco_levels,
            [c.model_dump() for c in config.companies],
            config.wage_net,
            market,
        )
        company_income = eco["company_net"]
        work_income = eco["work_income_day"]

        gear_cost = mean_wear
        consumables = mean_ammo + mean_food + pill_cost
        # Rumus net Intel (positif = rugi): gear + consumables - incomes.
        # Battle loot di-skip (0) sampai mekaniknya bisa dipetakan.
        net_cost = gear_cost + consumables - (
            scrap_income + mean_cases + loot_income + company_income + work_income
        )
        gold_per_k = net_cost / (mean_damage / 1000) if mean_damage > 0 else 0.0

        breakdown = {
            "daily_damage": round(mean_damage, 2),
            "damage_std": round(std_damage, 2),
            "hits": round(mean_hits, 1),
            "gear_cost": round(gear_cost, 2),
            "consumables": round(consumables, 2),
            "scrap_income": round(scrap_income, 2),
            "case_income": round(mean_cases, 2),
            "battle_loot_income": round(loot_income, 2),
            "company_income": round(company_income, 2),
            "work_income": round(work_income, 2),
            "net_cost": round(net_cost, 2),
            "gold_per_k": round(gold_per_k, 4),
        }
        return BuildResult(
            name=config.name, mode=config.mode.value,
            window=config.window, breakdown=breakdown,
            detail=config.detail, overrides_used=overrides_used,
        )

    # --- compare store (session-only, tanpa DB; bucket terpisah per mode) ---
    @staticmethod
    def _bucket_key(key: str, mode: str) -> str:
        return f"{key}:{mode}"

    @staticmethod
    def _sort_entries(entries: list[dict], mode: str) -> list[dict]:
        """Urutkan tabel banding sesuai metrik mode (lihat docstring Mode)."""
        if mode == Mode.FARMER.value:
            return sorted(entries, key=lambda e: e["breakdown"]["case_income"],
                          reverse=True)
        if mode == Mode.GLASS_CANNON.value:
            # Damage tertinggi dulu; kalau seri, gold_per_k terendah menang.
            return sorted(entries, key=lambda e: (
                -e["breakdown"]["daily_damage"], e["breakdown"]["gold_per_k"]))
        return sorted(entries, key=lambda e: e["breakdown"]["gold_per_k"])

    def add_to_compare(self, key: str, result: BuildResult) -> list[dict]:
        """Simpan build ke keranjang banding modenya; kembalikan tabel terurut."""
        entry = {
            "name": result.name,
            "mode": result.mode,
            "window": result.window,
            "detail": result.detail,
            "breakdown": result.breakdown,
        }
        with _compare_lock:
            bucket = _compare_buckets.setdefault(self._bucket_key(key, result.mode), [])
            bucket.append(entry)
            del bucket[:-COMPARE_LIMIT]
            while len(_compare_buckets) > _MAX_BUCKETS:
                _compare_buckets.pop(next(iter(_compare_buckets)))
            return self._sort_entries(bucket, result.mode)

    def get_compare(self, key: str, mode: str) -> list[dict]:
        with _compare_lock:
            return self._sort_entries(
                list(_compare_buckets.get(self._bucket_key(key, mode), [])), mode)

    def clear_compare(self, key: str, mode: str) -> None:
        with _compare_lock:
            _compare_buckets.pop(self._bucket_key(key, mode), None)

    # --- pin skills (session-level, lintas mode; fondasi optimizer) ---
    # Clear compare TIDAK menghapus pins (sengaja): pin = preferensi sesi,
    # bukan isi keranjang banding.
    def set_pins(self, key: str, pins: dict[str, int]) -> dict[str, int]:
        """Ganti seluruh set pin sesi ini. Key harus di SKILLS, level 0-10."""
        clean: dict[str, int] = {}
        for skill, level in (pins or {}).items():
            if skill not in SKILLS:
                raise ValueError(f"pin skill tidak dikenal: {skill}")
            if not isinstance(level, int) or not 0 <= level <= SKILL_MAX_LEVEL:
                raise ValueError(f"pin {skill}: level harus 0-{SKILL_MAX_LEVEL}")
            clean[skill] = level
        with _compare_lock:
            _pin_buckets[f"{key}:pins"] = clean
            return dict(clean)

    def get_pins(self, key: str) -> dict[str, int]:
        """Pin skill sesi ini; {} bila belum ada."""
        with _compare_lock:
            return dict(_pin_buckets.get(f"{key}:pins", {}))
