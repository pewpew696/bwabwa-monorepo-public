"""
WarEra Combat Simulator v2 — Build Optimizer
Cari kombinasi skill + equipment terbaik berdasarkan target & constraints.

Pure Python, no Flask. Dipanggil oleh web_api/simulator_routes.py.
"""

from simulator.constants import *
from simulator.engine import calculate_base_stats, quick_simulate, calculate_daily_projection, simulate_session
from itertools import product
import time
import random

# Estimasi biaya 1 hit RNG (simulate_session), dipakai buat bagi budget waktu
# verifikasi final ke kandidat-kandidat pemenang (F016/optimizer redesign).
# Diukur empiris ~5.3-5.5us/hit; pakai 6us biar ada margin aman.
RNG_HIT_COST_SECONDS = 6e-6

# Key numerik yang di-average antar run Monte Carlo. `ending_hp` dan
# `stopped_early` sengaja tidak di-average (bukan metrik hasil).
_MONTE_CARLO_KEYS = (
    "hits_completed", "total_damage", "avg_damage_per_hit", "avg_hp_cost_per_hit",
    "crit_rate", "miss_rate", "dodge_rate", "net_profit", "total_costs",
    "loot_income", "ammo_cost", "food_cost", "equipment_wear_cost",
    "expected_cases", "expected_elite_cases", "ehp",
)


def _mean_run(runs: list[dict]) -> dict:
    """Rata-rata N hasil simulate_session jadi satu dict (mean ± std).
    Ambil mean dari run pertama sebagai basis, timpa key numerik dengan
    statistik agregat. `ending_hp` = mean (dipakai chaining antar fase).

    Juga menyediakan alias format quick_simulate (expected_*) yang dihitung
    DARI hasil RNG — supaya score_build bisa menskor hasil Monte Carlo
    tanpa menghitung ulang closed-form. Angkanya tetap murni RNG."""
    if len(runs) == 1:
        out = dict(runs[0])
        out["monte_carlo_runs"] = 1
        return out
    out = dict(runs[0])
    out["monte_carlo_runs"] = len(runs)
    for key in _MONTE_CARLO_KEYS:
        values = [float(r.get(key) or 0) for r in runs]
        mean = sum(values) / len(values)
        out[key] = round(mean, 4)
        if len(values) > 1:
            variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            out[key + "_std"] = round(variance ** 0.5, 4)
    out["ending_hp"] = round(sum(float(r.get("ending_hp") or 0) for r in runs) / len(runs), 2)
    out["stopped_early"] = any(r.get("stopped_early") for r in runs)
    # Alias format quick_simulate — semua diturunkan dari hasil RNG asli.
    hits = out.get("hits_completed") or 0
    if hits > 0:
        out["expected_damage_per_hit"] = out["avg_damage_per_hit"]
        out["expected_hp_cost_per_hit"] = out["avg_hp_cost_per_hit"]
        out["expected_case_per_hit"] = out["expected_cases"] / hits
        out["expected_elite_case_per_hit"] = out["expected_elite_cases"] / hits
    return out


# ============================================================
# 1. BUILD CONFIG — Input dari user
# ============================================================

class BuildConfig:
    """Semua input dari user untuk optimizer."""

    def __init__(self):
        # Fixed (tidak dioptimasi)
        self.char_level = 24
        self.rank_bonus_pct = 10.0  # Military Rank bonus % langsung (sample: lvl 33 Sergeant = 10.00%)
        self.battle_config = {
            "ammo_tier": "ammo",
            "pill_state": "none",
            "rank_bonus_pct": self.rank_bonus_pct,
            "battle_bonus_pct": 0,
            "is_revolt": False,
        }

        # Equipment (bisa di-lock atau dioptimasi)
        self.locked_equipment = {}  # {"weapon": {...}} — ga diubah optimizer
        self.rarity_cap = "Merah"  # max rarity yang boleh disaranin (legacy; diabaikan kalau allowed_rarities diisi)
        # Ceklis rarity bebas (bukan cap berurutan): tier mana saja yang boleh
        # dioptimasi. None/kosong = fallback ke rarity_cap (backward-compat).
        self.allowed_rarities = None  # mis. ["Biru", "Ungu", "Kuning"]

        # Skill locks
        self.locked_skills = {}  # {"loot_chance": 5} — ga diubah optimizer

        # Optimization target
        self.target = "dps"  # "dps"|"survival"|"profit"|"efficiency"|"balanced"
        self.weights = {"dps": 0.4, "survival": 0.3, "profit": 0.3}  # untuk balanced

        # Economy
        # NOTE (2026-08-22): _calculate_company_income() sekarang mendukung
        # format baru "companies": [{"ae_level": 6, "production_target": "Iron"}, ...]
        # untuk company yang produksi item berbeda-beda + netting chain internal.
        # Format lama (company_count/ae_levels/company_production single-item)
        # masih didukung sebagai fallback untuk backward-compat.
        self.economy_config = {
            "food_type": "Steak",
            "market_prices": {},   # idealnya dari cache realtime price_history (Supabase BwabwabwaBot)
            "companies": [],       # [{"ae_level": int, "production_target": str}, ...] — format baru
            "company_count": 0,    # dipakai kalau "companies" kosong (fallback lama)
            "ae_levels": [],
            "company_production": None,  # default "Iron" kalau kosong (lihat engine.py)
            "weapon_rarity": "Hijau",
            "case_value": DEFAULT_CASE_VALUE,      # fallback kalau "Case 1" ga ada di market_prices live (fix 2026-08-28, sebelumnya placeholder 500.0)
            "elite_case_value": DEFAULT_ELITE_CASE_VALUE,  # fallback "Case 2" (sebelumnya placeholder 50000.0)
        }

        # Constraints
        self.max_results = 5  # return top N builds FINAL (setelah RNG-verify)
        self.hits_per_day = 300  # dipakai untuk scoring target "profit"/"balanced"

        # ── Search pipeline tuning (optimizer redesign 2026-09-03) ──
        self.raw_skill_pool_size = 3000   # kandidat skill mentah (random sampling), sebelumnya cuma 23
        self.skill_shortlist_size = 15    # top-N skill allocation yang lanjut ke equipment stage
        self.equipment_beam_width = 30    # lebar beam search cross-slot equipment
        self.rng_verify_seconds = 3.0     # budget waktu verifikasi RNG asli utk max_results kandidat final
        # Monte Carlo per kandidat final (keputusan owner 2026-10: angka yang
        # tampil ke user harus RNG asli yang stabil, bukan 1 run berisik).
        # 0 = pakai mekanisme rng_verify_seconds lama (backward-compat).
        self.rng_verify_runs = 0
        self.rng_verify_hits_per_run = 200

    def resolve_allowed_rarities(self) -> list[str]:
        """Rarity yang boleh dioptimasi. Sumber kebenaran: allowed_rarities
        (ceklis bebas user). Fallback: rarity_cap berurutan (legacy), dengan
        aturan lama: Putih dibuang kecuali cap-nya sendiri Putih."""
        if self.allowed_rarities:
            allowed = [r for r in RARITY_ORDER if r in set(self.allowed_rarities)]
            if allowed:
                return allowed
        cap_idx = RARITY_ORDER.index(self.rarity_cap)
        allowed = [r for r in RARITY_ORDER[:cap_idx + 1] if r != "Putih"]
        return allowed or RARITY_ORDER[:cap_idx + 1]


# ============================================================
# 2. SCORE FUNCTION — Sesuai target
# ============================================================

def score_build(stats: dict, sim_result: dict, target: str,
                weights: dict = None, economy_config: dict = None,
                hits_per_day: int = 300, equipment: dict = None,
                battle_config: dict = None) -> float:
    """
    Hitung score build berdasarkan target.
    Score lebih tinggi = build lebih baik.

    economy_config/hits_per_day/equipment/battle_config: kalau semuanya
    disediakan, target "profit"/"balanced" pakai net_profit_day/gold_per_k
    ASLI dari calculate_daily_projection() (income dikurangi ammo+food+wear
    cost sungguhan) — bukan proxy loot income kotor. Kalau salah satu tidak
    ada (mis. dipanggil dari test lama), fallback ke proxy kasar.
    """

    dps = sim_result["expected_damage_per_hit"]
    ehp = sim_result["ehp"] if sim_result["ehp"] != float("inf") else 999999
    hp_cost = sim_result["expected_hp_cost_per_hit"]
    case_rate = sim_result["expected_case_per_hit"]
    elite_rate = sim_result["expected_elite_case_per_hit"]

    can_compute_real_profit = (
        economy_config is not None and equipment is not None and battle_config is not None
    )

    if target == "dps":
        # Primary: DPS. Secondary: EHP as tie-breaker so non-DPS slots
        # (chest/pants/boots) still prefer higher rarity for survival.
        return dps + (ehp * 0.01)

    elif target == "survival":
        # Bertahan selama mungkin
        return ehp

    elif target == "efficiency":
        # Damage per HP cost, with tiny EHP tie-breaker
        base = dps / hp_cost if hp_cost > 0 else 999999
        return base + (ehp * 0.001)

    elif target == "profit":
        if can_compute_real_profit:
            daily = calculate_daily_projection(
                sim_result, stats, battle_config, economy_config,
                hits_per_day, equipment=equipment,
            )
            # Primary: net profit/day (income - ammo/food/wear cost) yang sungguhan.
            # Tie-breaker kecil pakai DPS supaya kalau net profit imbang, build yang
            # tetap kontribusi damage lebih besar tidak diabaikan.
            return daily["daily_net_profit"] + (dps * 0.001)
        # Fallback: proxy kasar (loot income kotor, belum dikurangi cost) —
        # dipakai kalau caller belum kirim economy_config/equipment/battle_config.
        # Revisi 2026-10-08: pakai harga case real dari constants (3.6/22.5,
        # user-confirmed 2026-08-28), bukan placeholder 500/50000 yang meleset ~140x.
        loot_score = (case_rate * DEFAULT_CASE_VALUE) + (elite_rate * DEFAULT_ELITE_CASE_VALUE)
        return loot_score + (dps * 0.01) + (ehp * 0.001)

    elif target == "balanced":
        # Weighted combination — normalize dulu
        w = weights or {"dps": 0.4, "survival": 0.3, "profit": 0.3}
        dps_n = min(1.0, dps / 5000)
        ehp_n = min(1.0, ehp / 1000)
        if can_compute_real_profit:
            # TODO: gold_per_k pakai net profit asli, tapi skala normalisasi
            # "berapa gold_per_k dianggap bagus" belum ada datanya — masih
            # pakai proxy loot kotor untuk komponen ini sampai ada acuan skala.
            pass
        profit_n = min(1.0, ((case_rate * DEFAULT_CASE_VALUE)
                            + (elite_rate * DEFAULT_ELITE_CASE_VALUE)) / 1000)
        return w["dps"] * dps_n + w["survival"] * ehp_n + w["profit"] * profit_n

    return dps  # fallback


# ============================================================
# 3. SKILL ALLOCATION OPTIMIZER
# ============================================================

def optimize_skills(config: BuildConfig) -> list[dict]:
    """
    Cari alokasi skill terbaik untuk maximize target.

    Strategi: Greedy dengan constraint SP budget.
    Untuk setiap kombinasi equipment, coba beberapa alokasi skill
    yang masuk akal (bukan brute force 11^10).

    Returns: list of {allocation, score, sp_used} sorted by score desc.
    """

    char_level = config.char_level
    sp_budget = max_sp_at_char_level(char_level)  # total asli, JANGAN di-overwrite

    # ── Company SP awareness (Fix #6) ──
    # Hitung total SP yang sudah terpakai oleh SEMUA locked skills (termasuk companies)
    # supaya _generate_skill_candidates tahu batasnya untuk combat skills saja.
    sp_used_locked = 0
    for key, level in config.locked_skills.items():
        sp_used_locked += level * (level + 1) // 2

    # Budget untuk candidate combat skills = total - semua locked (companies included)
    sp_available = sp_budget - sp_used_locked

    # Skills yang dioptimasi (exclude locked + excluded)
    optimizable_skills = []
    for key, skill in SKILLS.items():
        if key in SKILLS_EXCLUDED:
            continue
        if key in config.locked_skills:
            continue
        # Cek unlock level
        if char_level < skill["unlock"]:
            continue
        optimizable_skills.append(key)

    # ── Strategy: Generate candidate allocations ──
    # Bukan brute force 11^10 (2.6 miliar), tapi smart candidates:
    # 1. Max each combat skill individually
    # 2. Balanced spread
    # 3. DPS-focused (attack + crit + precision)
    # 4. Survival-focused (armor + dodge + health)
    # 5. Loot-focused (loot_chance maxed)
    # 6. Hybrid combinations

    candidates = _generate_skill_candidates(
        optimizable_skills, sp_available, char_level,
        pool_size=config.raw_skill_pool_size,
    )

    # ── Evaluate each candidate ──
    results = []

    for allocation in candidates:
        # Merge locked skills
        full_allocation = {**config.locked_skills, **allocation}

        # Cek SP budget
        sp_used = total_sp_for_allocation(full_allocation)
        if sp_used > sp_budget:
            continue

        # Build equipment (pakai config atau default)
        equipment = _build_equipment_from_config(config)

        # Calculate stats
        stats = calculate_base_stats(full_allocation, equipment, char_level)

        # Quick simulate
        sim = quick_simulate(stats, config.battle_config)

        # Score
        score = score_build(
            stats, sim, config.target, config.weights,
            economy_config=config.economy_config,
            hits_per_day=config.hits_per_day,
            equipment=equipment,
            battle_config=config.battle_config,
        )

        results.append({
            "skills": full_allocation,
            "sp_used": sp_used,
            "sp_budget": sp_budget,
            "score": round(score, 4),
            "stats": {
                "attack": stats["attack"],
                "precision_prob": round(stats["precision_prob"], 4),
                "crit_chance_prob": round(stats["crit_chance_prob"], 4),
                "crit_dmg_mult": round(stats["crit_dmg_mult"], 2),
                "armor_eff": round(stats["armor_eff"], 4),
                "dodge_eff": round(stats["dodge_eff"], 4),
                "max_hp": stats["max_hp"],
                "loot_chance_pct": stats["loot_chance_pct"],
            },
            "sim": sim,
        })

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate (beberapa candidates mungkin sama)
    seen = set()
    unique = []
    for r in results:
        key = tuple(sorted(r["skills"].items()))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    # ── Coordinate-ascent refinement (2026-09-03) ──
    # Ambil top-20 hasil random-sampling, coba naik/turunin tiap skill ±1
    # (respect SP budget & SKILL_MAX_LEVEL). Murah (~20 kandidat x ~2 skill x
    # 2 arah), tapi nutup celah kalau random sampling kelewat kombinasi bagus
    # yang deket kandidat top.
    refined = []
    for base in unique[:20]:
        for skill in optimizable_skills:
            for delta in (1, -1):
                trial = dict(base["skills"])
                trial[skill] = trial.get(skill, 0) + delta
                if trial[skill] < 0 or trial[skill] > SKILL_MAX_LEVEL:
                    continue
                if total_sp_for_allocation(trial) > sp_budget:
                    continue

                equipment = _build_equipment_from_config(config)
                stats = calculate_base_stats(trial, equipment, char_level)
                sim = quick_simulate(stats, config.battle_config)
                score = score_build(
                    stats, sim, config.target, config.weights,
                    economy_config=config.economy_config,
                    hits_per_day=config.hits_per_day,
                    equipment=equipment,
                    battle_config=config.battle_config,
                )
                refined.append({
                    "skills": trial,
                    "sp_used": total_sp_for_allocation(trial),
                    "sp_budget": sp_budget,
                    "score": round(score, 4),
                    "stats": {
                        "attack": stats["attack"],
                        "precision_prob": round(stats["precision_prob"], 4),
                        "crit_chance_prob": round(stats["crit_chance_prob"], 4),
                        "crit_dmg_mult": round(stats["crit_dmg_mult"], 2),
                        "armor_eff": round(stats["armor_eff"], 4),
                        "dodge_eff": round(stats["dodge_eff"], 4),
                        "max_hp": stats["max_hp"],
                        "loot_chance_pct": stats["loot_chance_pct"],
                    },
                    "sim": sim,
                })

    combined = unique + refined
    combined.sort(key=lambda x: x["score"], reverse=True)
    seen2 = set()
    final_unique = []
    for r in combined:
        key = tuple(sorted(r["skills"].items()))
        if key not in seen2:
            seen2.add(key)
            final_unique.append(r)

    # skill_shortlist_size: berapa kandidat skill yang lanjut ke equipment
    # stage — TERPISAH dari max_results (jumlah build FINAL yang ditampilkan),
    # supaya nggak kejadian lagi "nyaring 23 -> 15" alias hampir ga nyaring.
    return final_unique[:config.skill_shortlist_size]


def _generate_skill_candidates(skills, sp_available, char_level, pool_size=3000):
    """Generate kandidat alokasi skill. Precision WAJIB high priority.

    Sebelumnya cuma 23 kandidat tangan (5 preset + fokus + midpoint) — hampir
    nggak nyaring apa-apa kalau max_results mendekati itu. Sekarang ditambah
    `pool_size` kandidat random-sampling (valid terhadap SP budget), supaya
    raw pool beneran representatif sebelum di-filter (keputusan 2026-09-03)."""

    candidates = []

    # ── Presets: semua punya precision tinggi ──
    presets = {
        "dps": {
            "attack": 10, "precision": 10, "crit_chance": 10,
            "crit_damage": 10, "armor": 0, "dodge": 0,
            "health": 0, "hunger": 0, "loot_chance": 0, "companies": 0,
        },
        "survival": {
            "attack": 5, "precision": 8, "crit_chance": 0,
            "crit_damage": 0, "armor": 10, "dodge": 10,
            "health": 10, "hunger": 5, "loot_chance": 0, "companies": 0,
        },
        "loot": {
            "attack": 5, "precision": 8, "crit_chance": 0,
            "crit_damage": 0, "armor": 5, "dodge": 5,
            "health": 5, "hunger": 5, "loot_chance": 10, "companies": 0,
        },
        "balanced": {
            "attack": 7, "precision": 8, "crit_chance": 5,
            "crit_damage": 5, "armor": 5, "dodge": 5,
            "health": 5, "hunger": 5, "loot_chance": 3, "companies": 0,
        },
        "efficiency": {
            "attack": 10, "precision": 10, "crit_chance": 5,
            "crit_damage": 5, "armor": 7, "dodge": 7,
            "health": 5, "hunger": 5, "loot_chance": 0, "companies": 0,
        },
    }

    for preset_name, preset in presets.items():
        sp_needed = total_sp_for_allocation(preset)
        if sp_needed > sp_available:
            scaled = _scale_allocation(preset, sp_available)
            candidates.append(scaled)
        else:
            remaining = sp_available - sp_needed
            boosted = _distribute_remaining(preset, remaining, preset_name)
            candidates.append(boosted)

    # ── Greedy: max 1 skill + distribute sisanya ──
    for focus_skill in skills:
        if focus_skill == "precision":
            continue  # sudah di-handle oleh semua preset
        alloc = {s: 0 for s in skills}
        alloc[focus_skill] = 10
        # WAJIB isi precision dulu sebelum distribute
        alloc["precision"] = 5  # minimum 75% hit rate
        sp_used = total_sp_for_allocation(alloc)
        remaining = sp_available - sp_used
        if remaining >= 0:
            alloc = _distribute_remaining(alloc, remaining, "dps")
            candidates.append(alloc)

    # ── Mid-point: precision + 1 skill lain ──
    for s1 in skills:
        if s1 == "precision":
            continue
        alloc = {s: 0 for s in skills}
        alloc["precision"] = 8
        alloc[s1] = 5
        sp_used = total_sp_for_allocation(alloc)
        remaining = sp_available - sp_used
        if remaining >= 0:
            alloc = _distribute_remaining(alloc, remaining, "balanced")
            candidates.append(alloc)

    # ── Random sampling: perlebar raw pool (2026-09-03) ──
    # Shuffle urutan skill tiap kali, isi level acak per skill selama SP masih
    # ada. Nggak uniform sempurna, tapi cukup buat eksplorasi ruang alokasi
    # yang jauh lebih luas dari cuma preset tangan.
    for _ in range(pool_size):
        alloc = {s: 0 for s in skills}
        remaining = sp_available
        shuffled = list(skills)
        random.shuffle(shuffled)
        for s in shuffled:
            if remaining <= 0:
                break
            # Cari level maksimum yang affordable dari sisa SP utk skill ini
            max_affordable = 0
            spent_probe = 0
            for lvl in range(1, SKILL_MAX_LEVEL + 1):
                if spent_probe + lvl <= remaining:
                    spent_probe += lvl
                    max_affordable = lvl
                else:
                    break
            if max_affordable <= 0:
                continue
            level = random.randint(0, max_affordable)
            alloc[s] = level
            remaining -= (level * (level + 1)) // 2
        candidates.append(alloc)

    return candidates


def _scale_allocation(alloc: dict, sp_budget: int) -> dict:
    """Scale down alokasi agar muat SP budget."""
    result = dict(alloc)
    while total_sp_for_allocation(result) > sp_budget:
        # Cari skill tertinggi yang > 0, kurangi 1
        max_skill = max(result, key=result.get)
        if result[max_skill] > 0:
            result[max_skill] -= 1
        else:
            break
    return result


def _distribute_remaining(alloc, sp_remaining, preset_name):
    """Distribusikan sisa SP. Precision SELALU top priority."""
    result = dict(alloc)
    
    # Precision WAJIB di atas untuk semua preset
    priority = {
        "dps": ["precision", "attack", "crit_chance", "crit_damage", "health", "armor", "dodge"],
        "survival": ["precision", "armor", "dodge", "health", "hunger", "attack"],
        "loot": ["precision", "loot_chance", "dodge", "armor", "health", "attack"],
        "balanced": ["precision", "attack", "armor", "health", "dodge", "crit_chance"],
        "efficiency": ["precision", "attack", "armor", "dodge", "crit_chance", "health"],
    }
    prio = priority.get(preset_name, priority["balanced"])
    
    for skill in prio:
        if skill not in result:
            continue
        while result[skill] < SKILL_MAX_LEVEL and sp_remaining > 0:
            cost = result[skill] + 1
            if sp_remaining >= cost:
                result[skill] += 1
                sp_remaining -= cost
            else:
                break
    
    return result


# ============================================================
# 4. EQUIPMENT OPTIMIZER
# ============================================================

def optimize_equipment(config: BuildConfig,
                      skill_allocation: dict) -> list[dict]:
    """
    Cari equipment terbaik lintas-slot berdasarkan skill allocation.

    Strategi (redesign 2026-09-03): BEAM SEARCH cross-slot, bukan independent
    per-slot lagi. Proses slot satu-satu, tiap step simpan top-W kombinasi
    PARSIAL terbaik (bukan cuma 1), baru lanjut ke slot berikutnya — jadi
    keputusan tiap slot mempertimbangkan slot lain yang sudah dipilih, bukan
    buta terhadap efek gabungan. Ditutup dengan coordinate-ascent refinement
    (coba tukar 1 slot pada solusi terbaik, ulangi sampai nggak ada
    perbaikan) buat nutup celah kalau beam search kelewat kombinasi bagus.

    Rarity "Putih" DIBUANG dari ruang pencarian (user: nggak logis, nggak
    akan pernah menang lawan rarity lebih tinggi di stat range yang sama).

    Returns: list of equipment configs sorted by score (1 hasil terbaik).
    """

    char_level = config.char_level
    allowed_rarities = config.resolve_allowed_rarities()

    # ── Generate equipment candidates per slot ──
    slot_candidates = {}

    for slot, stat_types in SLOT_STAT_MAP.items():
        if slot in config.locked_equipment:
            # Locked — pakai yang ada
            slot_candidates[slot] = [config.locked_equipment[slot]]
            continue

        candidates = []
        for rarity in allowed_rarities:
            # Untuk setiap rarity, coba 3 nilai: min, mid, max
            for stat_type in stat_types:
                rng = get_stat_range(stat_type, rarity)
                if not rng:
                    continue
                mn, mx = rng
                for val in [mn, (mn + mx) // 2, mx]:
                    eq = {
                        "rarity": rarity,
                        "stats": {stat_type: val},
                        "durability": 100,
                    }
                    # Untuk slot dengan 2 stats (weapon), isi stat kedua juga
                    if len(stat_types) > 1:
                        for other_stat in stat_types:
                            if other_stat != stat_type:
                                other_rng = get_stat_range(other_stat, rarity)
                                if other_rng:
                                    eq["stats"][other_stat] = other_rng[1]  # mid value
                    candidates.append(eq)

        slot_candidates[slot] = candidates or [_default_equipment(slot, allowed_rarities)]

    def _score_partial(partial_eq: dict) -> float:
        """Skor 1 kombinasi equipment PENUH (slot kosong diisi default dulu)."""
        temp_eq = dict(partial_eq)
        for other_slot in SLOT_STAT_MAP:
            if other_slot not in temp_eq:
                temp_eq[other_slot] = config.locked_equipment.get(
                    other_slot, _default_equipment(other_slot, allowed_rarities)
                )
        stats = calculate_base_stats(skill_allocation, temp_eq, char_level)
        sim = quick_simulate(stats, config.battle_config)
        return score_build(
            stats, sim, config.target, config.weights,
            economy_config=config.economy_config,
            hits_per_day=config.hits_per_day,
            equipment=temp_eq,
            battle_config=config.battle_config,
        )

    # ── Beam search cross-slot ──
    beam_width = max(1, config.equipment_beam_width)
    beam = [({}, -1.0)]  # list of (partial_equipment, score)

    for slot in SLOT_STAT_MAP:
        if slot in config.locked_equipment:
            beam = [({**partial, slot: config.locked_equipment[slot]}, score)
                    for partial, score in beam]
            continue

        expanded = []
        for partial, _ in beam:
            for eq in slot_candidates.get(slot, []):
                trial = dict(partial)
                trial[slot] = eq
                expanded.append((trial, _score_partial(trial)))

        expanded.sort(key=lambda x: x[1], reverse=True)
        beam = expanded[:beam_width]

    best_equipment, best_score = beam[0]

    # ── Coordinate-ascent refinement ──
    # Coba tukar 1 slot pada solusi terbaik dari beam search, ulangi sampai
    # nggak ada perbaikan lagi. Murah (~6 slot x ~15-30 kandidat), nutup
    # celah kalau beam width kelewat kombinasi bagus.
    improved = True
    while improved:
        improved = False
        for slot in SLOT_STAT_MAP:
            if slot in config.locked_equipment:
                continue
            for eq in slot_candidates.get(slot, []):
                trial = dict(best_equipment)
                trial[slot] = eq
                score = _score_partial(trial)
                if score > best_score:
                    best_score = score
                    best_equipment = trial
                    improved = True

    # ── Calculate final stats with best equipment ──
    stats = calculate_base_stats(skill_allocation, best_equipment, char_level)
    sim = quick_simulate(stats, config.battle_config)
    score = score_build(
        stats, sim, config.target, config.weights,
        economy_config=config.economy_config,
        hits_per_day=config.hits_per_day,
        equipment=best_equipment,
        battle_config=config.battle_config,
    )

    return [{
        "equipment": best_equipment,
        "score": round(score, 4),
        "stats": {
            "attack": stats["attack"],
            "precision_prob": round(stats["precision_prob"], 4),
            "crit_chance_prob": round(stats["crit_chance_prob"], 4),
            "crit_dmg_mult": round(stats["crit_dmg_mult"], 2),
            "armor_eff": round(stats["armor_eff"], 4),
            "dodge_eff": round(stats["dodge_eff"], 4),
            "max_hp": stats["max_hp"],
            "loot_chance_pct": stats["loot_chance_pct"],
        },
        "sim": sim,
    }]


def _default_equipment(slot: str, allowed_rarities: list) -> dict:
    """Default equipment: rarity tertinggi yang allowed, stat mid."""
    rarity = allowed_rarities[-1]  # highest allowed
    stat_types = SLOT_STAT_MAP.get(slot, [])
    stats = {}
    for st in stat_types:
        rng = get_stat_range(st, rarity)
        if rng:
            stats[st] = (rng[0] + rng[1]) // 2  # mid value
    return {"rarity": rarity, "stats": stats, "durability": 100}


def _build_equipment_from_config(config: BuildConfig) -> dict:
    """Build equipment dict dari config (locked + defaults)."""
    allowed = config.resolve_allowed_rarities()
    equipment = {}
    for slot in EQUIPMENT_SLOTS:
        if slot in config.locked_equipment:
            equipment[slot] = config.locked_equipment[slot]
        else:
            equipment[slot] = _default_equipment(slot, allowed)
    return equipment


# ============================================================
# 5. FULL OPTIMIZER — Skill + Equipment
# ============================================================

def optimize_build(config: BuildConfig) -> dict:
    """
    Optimasi lengkap: cari kombinasi skill + equipment terbaik.

    Flow (redesign 2026-09-03):
    1. Cari skill_shortlist_size skill allocations (raw pool ribuan -> shortlist)
    2. Untuk setiap, cari equipment terbaik (beam search cross-slot + refinement)
    3. Re-score dengan equipment optimal (closed-form, cepat — buat RANKING doang)
    4. Ambil top max_results overall
    5. Verifikasi max_results kandidat FINAL itu pakai RNG asli
       (simulate_session), hit count dibagi dari rng_verify_seconds budget —
       INI yang ditampilkan ke user, bukan angka closed-form (keputusan
       "cuma satu cara, pakai RNG" 2026-09-02)

    Returns: {
        "best": {skills, equipment, score, stats, sim, rng_verified},
        "alternatives": [...],
        "config": config summary,
    }
    """

    start_time = time.time()

    # Step 1: Optimize skills (shortlist, BUKAN hardcode [:10] lagi —
    # skill_shortlist_size sudah proper terpisah dari max_results)
    skill_results = optimize_skills(config)

    # Step 2: For each shortlisted skill allocation, optimize equipment
    full_results = []

    for sr in skill_results:
        eq_results = optimize_equipment(config, sr["skills"])

        for eq_r in eq_results:
            # Recalculate with optimal equipment
            stats = calculate_base_stats(
                sr["skills"], eq_r["equipment"], config.char_level
            )
            sim = quick_simulate(stats, config.battle_config)
            score = score_build(
                stats, sim, config.target, config.weights,
                economy_config=config.economy_config,
                hits_per_day=config.hits_per_day,
                equipment=eq_r["equipment"],
                battle_config=config.battle_config,
            )

            full_results.append({
                "skills": sr["skills"],
                "equipment": eq_r["equipment"],
                "score": round(score, 4),
                "sp_used": sr["sp_used"],
                "sp_budget": sr["sp_budget"],
                "stats": {
                    "attack": stats["attack"],
                    "precision_prob": round(stats["precision_prob"], 4),
                    "crit_chance_prob": round(stats["crit_chance_prob"], 4),
                    "crit_dmg_mult": round(stats["crit_dmg_mult"], 2),
                    "armor_eff": round(stats["armor_eff"], 4),
                    "dodge_eff": round(stats["dodge_eff"], 4),
                    "max_hp": stats["max_hp"],
                    "loot_chance_pct": stats["loot_chance_pct"],
                    "_breakdown": stats["_breakdown"],
                },
                "sim": sim,
            })

    # Sort all by score
    full_results.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate
    seen = set()
    unique = []
    for r in full_results:
        # Key: skill allocation + equipment rarities
        skill_key = tuple(sorted(r["skills"].items()))
        eq_key = tuple(
            (s, e.get("rarity", "")) for s, e in sorted(r["equipment"].items())
        )
        key = (skill_key, eq_key)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    top = unique[:config.max_results]

    # ── RNG verification (2026-09-02: "cuma satu cara, pakai RNG asli") ──
    # top sudah diranking closed-form (cepat). Kandidat final dijalankan ulang
    # pakai simulate_session() beneran. Hasil INI yang ditampilkan ke user,
    # bukan quick_simulate (closed-form cuma buat ranking internal).
    #
    # 2026-10: dua mode verifikasi:
    #   - rng_verify_runs > 0 : Monte Carlo N run × hits_per_run per kandidat,
    #     ranking final pakai MEAN hasil RNG (angka stabil, mean ± std)
    #   - rng_verify_runs = 0 : mode lama, 1 run per kandidat dengan hit count
    #     dibagi dari rng_verify_seconds budget (backward-compat)
    if top:
        if config.rng_verify_runs > 0:
            for r in top:
                runs = []
                for _ in range(config.rng_verify_runs):
                    runs.append(simulate_session(
                        calculate_base_stats(r["skills"], r["equipment"], config.char_level),
                        config.battle_config, config.economy_config,
                        num_hits=config.rng_verify_hits_per_run, equipment=r["equipment"],
                    ))
                r["rng_verified"] = _mean_run(runs)
                r["rng_verify_hits"] = config.rng_verify_hits_per_run
                r["rng_verify_runs"] = config.rng_verify_runs
                # Score final = skor RNG asli (bukan closed-form) — dipakai
                # untuk urutan tampil di hasil.
                r["score"] = score_build(
                    calculate_base_stats(r["skills"], r["equipment"], config.char_level),
                    r["rng_verified"], config.target, config.weights,
                    economy_config=config.economy_config,
                    equipment=r["equipment"],
                    battle_config=config.battle_config,
                    hits_per_day=config.hits_per_day,
                )
            top.sort(key=lambda r: -r["score"])
        else:
            hits_per_candidate = max(
                100, int(config.rng_verify_seconds / (len(top) * RNG_HIT_COST_SECONDS))
            )
            for r in top:
                rng_result = simulate_session(
                    calculate_base_stats(r["skills"], r["equipment"], config.char_level),
                    config.battle_config, config.economy_config,
                    num_hits=hits_per_candidate, equipment=r["equipment"],
                )
                r["rng_verified"] = rng_result
                r["rng_verify_hits"] = hits_per_candidate

    elapsed = round(time.time() - start_time, 3)

    return {
        "best": top[0] if top else None,
        "alternatives": top[1:] if len(top) > 1 else [],
        "total_candidates": len(full_results),
        "elapsed_seconds": elapsed,
        "config": {
            "char_level": config.char_level,
            "rank_bonus_pct": config.rank_bonus_pct,
            "target": config.target,
            "rarity_cap": config.rarity_cap,
            "locked_skills": config.locked_skills,
            "locked_equipment": list(config.locked_equipment.keys()),
            "raw_skill_pool_size": config.raw_skill_pool_size,
            "skill_shortlist_size": config.skill_shortlist_size,
            "equipment_beam_width": config.equipment_beam_width,
        },
    }
