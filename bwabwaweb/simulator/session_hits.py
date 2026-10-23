# simulator/session_hits.py — simulasi sesi & estimasi jumlah hit

import logging

from simulator.constants import (
    AMMO_REF_PRICES,
    BASE_HEALTH_COST,
    DEFAULT_CASE_VALUE,
    DEFAULT_ELITE_CASE_VALUE,
    EQUIPMENT_SLOTS,
    FOOD_ITEMS,
    HP_REGEN_PCT_PER_HOUR,
    HUNGER_REGEN_PCT_PER_HOUR,
    PILL_BUFF_DURATION_HOURS,
    PILL_DEBUFF_DURATION_HOURS,
    PILL_NEUTRAL_DURATION_HOURS,
    SESSION_END_RESOURCE_PCT,
    SESSION_HOURS,
    WINDOW_HOURS,
)
from simulator.economy_quick import (
    _calculate_company_income,
    _calculate_equipment_wear_cost,
    _needs_ammo,
)
from simulator.stats_combat import execute_combat_action

log = logging.getLogger("WarEraBot.session_hits")


# --- session simulation ---
def simulate_session(
    stats: dict,
    battle_config: dict,
    economy_config: dict,
    num_hits: int = 100,
    equipment: dict = None,
    regen_pool: float = None,
    hunger_budget: float = None,
    starting_hp: float = None,
) -> dict:
    """
    Simulasikan sesi farming (N hits) dan agregasi hasil.

    Args:
        stats: output dari calculate_base_stats()
        battle_config: battle scenario config
        economy_config: {
            "food_type": "Steak",          # "Bread"|"Steak"|"Cooked Fish"
            "market_prices": {             # dari _bot._price_cache atau manual
                "Light Ammo": 0.20,
                "Ammo": 0.72,
                "Heavy Ammo": 2.70,
                "Bread": 5.0,
                "Steak": 12.0,
                "Cooked Fish": 15.0,
                # ... items lain untuk company income
            },
            "company_count": 5,
            "ae_levels": [3, 3, 3, 3, 3],
            "company_production": "Heavy Ammo",  # item yang diproduksi
            "weapon_rarity": "Ungu",  # menentukan butuh ammo atau tidak
        }
        num_hits: TARGET jumlah hit (biasanya dari calculate_max_hits()/
            plan_hit_budget() — F016). Sesi bisa berhenti LEBIH AWAL dari ini
            kalau resource abis duluan (lihat regen_pool/hunger_budget).
        equipment: {"weapon": {"rarity": ...}, ...} — dipakai untuk hitung
            wear cost per-rarity dari craft cost (scrap+steel), sama seperti
            calculate_daily_projection(). Kalau kosong, semua slot dianggap
            rarity "Putih" (craft cost termurah).
        regen_pool: jatah HP gratis dari regen selama window (F016, dari
            calculate_max_hits()["regen_pool"]). None = unlimited (perilaku
            lama, backward-compat).
        hunger_budget: jatah makan maksimal — unit hunger, 1 food = -1 (F016,
            dari calculate_max_hits()["hunger_budget"]). None = unlimited.
        starting_hp: HP awal sesi ini (buat chaining antar-fase, mis. fase
            debuff yang nyambung dari sisa HP fase buff). None = max_hp penuh.

    Returns: agregasi damage, resource cost, economy. Kalau resource abis
        sebelum num_hits tercapai, `hits_completed` < num_hits dan
        `stopped_early=True` (auto-stop natural, BUKAN dipaksa — RNG apes
        berarti hasil di bawah target, itu jujur bukan bug).
    """

    # ── Simulation loop ──
    total_damage = 0
    total_hp_cost = 0
    total_durability_loss = {slot: 0 for slot in EQUIPMENT_SLOTS}
    total_ammo_used = 0
    total_crits = 0
    total_misses = 0
    total_dodges = 0
    total_case_chances = 0
    total_elite_case_chances = 0
    food_eaten = 0
    regen_pool_used = 0.0
    hits_completed = 0
    stopped_early = False

    max_hp = stats["max_hp"]
    current_hp = starting_hp if starting_hp is not None else max_hp
    regen_pool_left = regen_pool if regen_pool is not None else float("inf")
    hunger_budget_left = hunger_budget if hunger_budget is not None else float("inf")

    # ── Food heal % (Fix #3: handle "none" food_type) ──
    food_type = economy_config.get("food_type", "Steak")
    if food_type == "none" or food_type is None:
        food_heal_pct = 0
    else:
        food_heal_pct = FOOD_ITEMS.get(food_type, FOOD_ITEMS["Steak"])["heal_pct"]

    weapon_rarity = (equipment or {}).get("weapon", {}).get("rarity", "Hijau")
    ammo_tier = battle_config.get("ammo_tier", "ammo")
    # Fix #4: "none" ammo_tier or "knife" ammo = no ammo needed
    needs_ammo = _needs_ammo(weapon_rarity, ammo_tier)

    for _ in range(num_hits):
        # Execute 1 hit
        result = execute_combat_action(stats, battle_config)

        total_damage += result["damage_contribution"]
        total_hp_cost += result["health_cost"]
        total_crits += 1 if result["is_crit"] else 0
        total_misses += 1 if result["is_miss"] else 0
        total_dodges += 1 if result["is_dodged"] else 0
        total_case_chances += result["case_chance"]
        total_elite_case_chances += result["elite_case_chance"]

        # Durability
        for slot, loss in result["durability_loss"].items():
            total_durability_loss[slot] += loss

        # Ammo (1 per hit if weapon needs ammo)
        if needs_ammo:
            total_ammo_used += 1

        # HP management — heal pas HP <= 30% max_hp. Sumber heal: regen_pool
        # (gratis, ga makan hunger) atau food (makan hunger_budget). Urutan
        # antara keduanya ga penting secara hasil (user 2026-09-03) — pakai
        # regen_pool dulu selama masih ada, baru food.
        current_hp -= result["health_cost"]
        hits_completed += 1
        if current_hp <= max_hp * 0.30:
            heal_amount = max_hp * food_heal_pct
            if regen_pool_left > 0:
                used = min(regen_pool_left, heal_amount)
                regen_pool_left -= used
                regen_pool_used += used
                current_hp = min(max_hp, current_hp + used)
            elif hunger_budget_left >= 1:
                hunger_budget_left -= 1
                food_eaten += 1
                current_hp = min(max_hp, current_hp + heal_amount)
            # else: nggak ada resource lagi, current_hp tetap rendah

        if current_hp <= 0:
            stopped_early = True
            break

    # ── Expected values (averages, berbasis hit yang BENERAN kejadi) ──
    avg_damage = total_damage / hits_completed if hits_completed > 0 else 0
    avg_hp_cost = total_hp_cost / hits_completed if hits_completed > 0 else 0
    crit_rate = total_crits / hits_completed if hits_completed > 0 else 0
    miss_rate = total_misses / hits_completed if hits_completed > 0 else 0
    dodge_rate = total_dodges / hits_completed if hits_completed > 0 else 0

    # ── Economy calculation ──
    market = economy_config.get("market_prices", {})

    # Ammo cost (Fix #4: skip if ammo_tier is "none")
    ammo_cost = 0
    if ammo_tier not in ("none", "knife"):
        ammo_item_name = {
            "light": "Light Ammo",
            "ammo": "Ammo",
            "heavy": "Heavy Ammo",
        }.get(ammo_tier, "Ammo")
        ammo_price = market.get(ammo_item_name, AMMO_REF_PRICES.get(ammo_item_name, {}).get("min", 0))
        ammo_cost = total_ammo_used * ammo_price

    # Food cost (Fix #3: skip if food_type is "none")
    food_cost = 0
    if food_type not in ("none", None):
        food_name = food_type
        food_price = market.get(food_name, 10.0)
        food_cost = food_eaten * food_price

    # Expected loot income (case chance accumulated × case value)
    # Case value = harga live "Case 1" (normal) / "Case 2" (elite) dari market
    # cache, sama pola dengan ammo/food. Fallback ke economy_config manual
    # (kalau caller sengaja override), baru fallback statis kalau dua-duanya
    # kosong (user-confirmed 2026-08-28: Case 1 ≈ 3.6, Case 2 ≈ 22.5).
    case_value = market.get("Case 1", economy_config.get("case_value", DEFAULT_CASE_VALUE))
    elite_case_value = market.get("Case 2", economy_config.get("elite_case_value", DEFAULT_ELITE_CASE_VALUE))
    loot_income = (total_case_chances * case_value) + (total_elite_case_chances * elite_case_value)

    # Company income
    company_income = _calculate_company_income(economy_config, market)["net_income"]

    # Equipment wear cost — pakai craft cost per-rarity (scrap+steel di harga
    # market live), sama seperti calculate_daily_projection() (F011/F012,
    # tervalidasi terhadap sample WarEra Intel, lihat komentar di bawah).
    equipment_wear_cost = _calculate_equipment_wear_cost(
        total_durability_loss, equipment, market
    )

    # Net profit
    total_costs = ammo_cost + food_cost + equipment_wear_cost
    net_profit = loot_income + company_income - total_costs

    return {
        # Sesi
        "hits_requested": num_hits,
        "hits_completed": hits_completed,
        "stopped_early": stopped_early,  # True = resource abis sebelum num_hits tercapai (RNG apes, bukan bug)
        "ending_hp": round(current_hp, 2),
        "regen_pool_used": round(regen_pool_used, 2),
        # Combat stats
        "total_damage": total_damage,
        "avg_damage_per_hit": round(avg_damage, 2),
        "total_hp_cost": round(total_hp_cost, 2),
        "avg_hp_cost_per_hit": round(avg_hp_cost, 2),
        "crit_rate": round(crit_rate, 4),
        "miss_rate": round(miss_rate, 4),
        "dodge_rate": round(dodge_rate, 4),
        # Resource
        "total_ammo_used": total_ammo_used,
        "total_durability_loss": total_durability_loss,
        "food_eaten": food_eaten,
        # Economy
        "ammo_cost": round(ammo_cost, 2),
        "food_cost": round(food_cost, 2),
        "equipment_wear_cost": round(equipment_wear_cost, 2),
        "loot_income": round(loot_income, 2),
        "company_income": round(company_income, 2),
        "net_profit": round(net_profit, 2),
        "total_costs": round(total_costs, 2),
        # Survival
        "ehp": round(max_hp / avg_hp_cost, 2) if avg_hp_cost > 0 else float("inf"),
        # Loot
        "expected_cases": round(total_case_chances, 4),
        "expected_elite_cases": round(total_elite_case_chances, 6),
    }




# ============================================================
# 2b. MAX HITS ESTIMATION — pengganti input manual num_hits (F016)
# ============================================================
# WarEra TIDAK punya cooldown attack — selama HP masih ada, pemain bisa hit
# terus (confirmed user 2026-09-03). Jadi jumlah hit yang bisa dicapai dalam
# window T jam murni dibatasi resource (HP), bukan waktu/kecepatan aksi.
# Base Health Cost = 10 itu FIX/konstan, cuma dipengaruhi armor_eff & dodge_eff
# (confirmed user, F010 no longer "Known Unknown" utk kasus ini).

def calculate_max_hits(stats: dict, hours: float, food_heal_pct: float,
                        starting_hp_pct: float = 1.0,
                        starting_hunger_pct: float = 1.0,
                        end_reserve_pct: float = 0.0) -> dict:
    """
    Estimasi max hit yang bisa dicapai (expected value, BUKAN hard cap —
    RNG asli di simulate_session() bisa beda) dalam window `hours` jam.

    Model "flow": pemain hit + makan berkelanjutan sepanjang window, jadi
    total budget = starting_hp + regen selama window + HP dari makan
    (hunger_budget = starting_hunger + regen hunger selama window, TIDAK
    dicap ke max_hunger karena representasi kumulatif "kapasitas makan"
    seiring waktu, bukan level statis — lihat calculate_debuff_maintenance_hits()
    untuk kasus hunger yang DIPERTAHANKAN/tidak dimakan).

    starting_hp_pct/starting_hunger_pct: fraksi (0.0-1.0) resource DI AWAL
    window ini. Default 1.0 (mulai penuh) untuk fase pertama / sesi biasa.
    Dipakai untuk chaining multi-fase (mis. fase "none" yang nyambung dari
    HP hasil maintenance fase debuff sebelumnya, bukan mulai dari nol).

    Args:
        stats: output dari calculate_base_stats() — gear fase INI (bisa beda
            per fase, mis. knife-only pas debuff)
        hours: durasi window (jam)
        food_heal_pct: dari FOOD_ITEMS[food_type]["heal_pct"]
        starting_hp_pct, starting_hunger_pct: fraksi starting resource (0-1)
        end_reserve_pct: fraksi max HP dan max hunger yang harus tersisa di akhir
            window (0 = boleh habis; fase none 24 jam memakai SESSION_END_RESOURCE_PCT)

    Returns: dict — regen_pool, hunger_budget, total_hp_budget, e_cost_per_hit,
        max_hits (estimasi).
    """
    max_hp = stats["max_hp"]
    max_hunger = stats["max_hunger"]
    dodge_eff = stats["dodge_eff"]
    armor_eff = stats["armor_eff"]

    starting_hp = max_hp * starting_hp_pct
    starting_hunger = max_hunger * starting_hunger_pct
    reserve_hp = max_hp * end_reserve_pct
    reserve_hunger = max_hunger * end_reserve_pct

    regen_pool = hours * HP_REGEN_PCT_PER_HOUR * max_hp
    hunger_regen = hours * HUNGER_REGEN_PCT_PER_HOUR * max_hunger
    hunger_budget = max(0.0, starting_hunger + hunger_regen - reserve_hunger)
    hp_from_food = hunger_budget * food_heal_pct * max_hp

    total_hp_budget = max(0.0, starting_hp + regen_pool + hp_from_food - reserve_hp)
    e_cost_per_hit = (1 - dodge_eff) * BASE_HEALTH_COST * (1 - armor_eff)
    max_hits = (total_hp_budget / e_cost_per_hit) if e_cost_per_hit > 0 else 0

    return {
        "hours": hours,
        "starting_hp": round(starting_hp, 2),
        "regen_pool": round(regen_pool, 2),
        "hunger_budget": round(hunger_budget, 2),
        "hp_from_food": round(hp_from_food, 2),
        "total_hp_budget": round(total_hp_budget, 2),
        "e_cost_per_hit": round(e_cost_per_hit, 4),
        "max_hits": int(max_hits),
    }


# --- debuff maintenance hits ---
def calculate_debuff_maintenance_hits(stats: dict, hours: float,
                                       starting_hp_pct: float = 0.0) -> dict:
    """
    Estimasi jumlah "token-maintenance hit" selama fase debuff pill.

    Strategi pemain (confirmed user 2026-09-03): karena debuff rugi (atk
    x0.4), pemain SENGAJA minim hit — cuma secukupnya biar regen HP nggak
    kebuang sia-sia pas udah mentok max_hp, dan SAMA SEKALI TIDAK MAKAN
    (hunger dibiarkan idle/numpuk penuh, disimpan buat fase berikutnya).

    Karena regen HP dicap di max_hp (nggak bisa numpuk lebih), hit
    "maintenance" cuma perlu nyerap bagian regen yang KELEBIHAN setelah HP
    mentok cap — bukan seluruh regen sepanjang window.

    Args:
        stats: output dari calculate_base_stats() — gear fase debuff
            (biasanya knife-only, lihat asumsi yang disepakati)
        hours: durasi fase debuff (jam)
        starting_hp_pct: fraksi HP di awal fase ini (biasanya ~0, abis
            dipakai burst di akhir fase sebelumnya)

    Returns: dict — time_to_cap (jam sampai HP nyampe 100%), regen_wasted_risk
        (HP worth yang perlu diserap), maintenance_hits (estimasi), dan
        ending_hunger_pct=1.0 (penuh, karena nggak disentuh sama sekali).
    """
    max_hp = stats["max_hp"]
    dodge_eff = stats["dodge_eff"]
    armor_eff = stats["armor_eff"]

    time_to_cap = (1.0 - starting_hp_pct) / HP_REGEN_PCT_PER_HOUR if HP_REGEN_PCT_PER_HOUR > 0 else 0
    time_at_risk = max(0.0, hours - time_to_cap)
    regen_at_risk = time_at_risk * HP_REGEN_PCT_PER_HOUR * max_hp

    e_cost_per_hit = (1 - dodge_eff) * BASE_HEALTH_COST * (1 - armor_eff)
    maintenance_hits = (regen_at_risk / e_cost_per_hit) if e_cost_per_hit > 0 else 0

    return {
        "hours": hours,
        "time_to_cap_hours": round(time_to_cap, 2),
        "regen_at_risk": round(regen_at_risk, 2),
        "e_cost_per_hit": round(e_cost_per_hit, 4),
        "maintenance_hits": int(round(maintenance_hits)),
        # Setelah fase ini: HP dijaga di sekitar cap (~100%), hunger 100%
        # (nggak disentuh sama sekali sepanjang fase debuff).
        "ending_hp_pct": 1.0,
        "ending_hunger_pct": 1.0,
    }


# --- plan hit budget ---
def _invalid_window(window: str) -> ValueError:
    return ValueError(f"window harus salah satu dari {list(WINDOW_HOURS)}, dapat: {window!r}")


def plan_hit_budget(build_full_stats: dict, build_debuff_stats: dict,
                     food_heal_pct: float, window: str,
                     buff_hours: float = PILL_BUFF_DURATION_HOURS,
                     debuff_hours: float = PILL_DEBUFF_DURATION_HOURS,
                     none_hours: float = PILL_NEUTRAL_DURATION_HOURS) -> dict:
    """
    Rencanakan total hit yang bisa dicapai untuk 1 sesi, ganti input manual
    num_hits (F016). Dipanggil sebelum simulate_session() — hasilnya (jumlah
    hit per fase) jadi target num_hits yang dijalankan RNG asli per fase.

    window: "8h" (cuma fase buff, gear lengkap, TANPA pill split),
        "16h" (buff buff_hours gear lengkap -> debuff sisa 16 - buff_hours
        jam knife-only, TANPA fase none),
        "24h" (3 fase: buff 8 jam gear lengkap -> debuff ~15,5 jam knife-only
        token-maintenance -> none 30 menit gear lengkap balik, total pas
        24 jam kalender). Durasi debuff 15,5 jam per user (bukan 16 jam
        versi dokumentasi tertulis) — buff_hours + debuff_hours = 23,5 jam,
        sisa 0,5 jam jadi fase "none" biar pas 24 jam kalender.

    Returns: dict per-fase (masing-masing hasil calculate_max_hits /
        calculate_debuff_maintenance_hits) + total_max_hits.
    """
    if window == "8h":
        buff = calculate_max_hits(build_full_stats, buff_hours, food_heal_pct,
                                   starting_hp_pct=1.0, starting_hunger_pct=1.0)
        return {
            "window": "8h",
            "phases": {"buff": buff},
            "total_max_hits": buff["max_hits"],
        }

    if window == "16h":
        # Buff + debuff saja, tanpa fase none (sisa window dipakai debuff)
        buff = calculate_max_hits(build_full_stats, buff_hours, food_heal_pct,
                                   starting_hp_pct=1.0, starting_hunger_pct=1.0)
        debuff = calculate_debuff_maintenance_hits(
            build_debuff_stats, WINDOW_HOURS["16h"] - buff_hours, starting_hp_pct=0.0
        )
        return {
            "window": "16h",
            "phases": {"buff": buff, "debuff": debuff},
            "total_max_hits": buff["max_hits"] + debuff["maintenance_hits"],
        }

    if window == "24h":
        # Fase 1: BUFF — burst di awal+akhir, gear lengkap, mulai penuh
        buff = calculate_max_hits(build_full_stats, buff_hours, food_heal_pct,
                                   starting_hp_pct=1.0, starting_hunger_pct=1.0)

        # Fase 2: DEBUFF — token-maintenance, knife-only, HP nyambung dr ~0
        # (abis dr burst akhir fase buff), hunger idle/disimpan penuh
        debuff = calculate_debuff_maintenance_hits(
            build_debuff_stats, debuff_hours, starting_hp_pct=0.0
        )

        # Fase 3: NONE — burst pakai HP yg di-maintain (~penuh dr fase debuff)
        # + hunger yg disimpan PENUH sepanjang fase debuff, gear lengkap lagi
        none_phase = calculate_max_hits(
            build_full_stats, none_hours, food_heal_pct,
            starting_hp_pct=debuff["ending_hp_pct"],
            starting_hunger_pct=debuff["ending_hunger_pct"],
            end_reserve_pct=SESSION_END_RESOURCE_PCT,  # sesi 24 jam berakhir di sisa akhir
        )

        total = buff["max_hits"] + debuff["maintenance_hits"] + none_phase["max_hits"]
        return {
            "window": "24h",
            "phases": {"buff": buff, "debuff": debuff, "none": none_phase},
            "total_max_hits": total,
        }

    raise _invalid_window(window)


def plan_hit_budget_no_pill(build_full_stats: dict, food_heal_pct: float, window: str) -> dict:
    """
    Rencanakan total hit tanpa pill: seluruh window = satu fase "none" (gear lengkap, burst
    di awal). Budget window dibatasi budget sesi 24 jam yang menyisakan
    SESSION_END_RESOURCE_PCT di akhir (8h/16h = jam pertama sesi itu), sama dengan sisi
    hunger di _hunger_food_per_day.

    Returns: dict bentuk sama dengan plan_hit_budget, satu fase "none".
    """
    if window not in WINDOW_HOURS:
        raise _invalid_window(window)
    window_phase = calculate_max_hits(build_full_stats, WINDOW_HOURS[window], food_heal_pct)
    session_phase = calculate_max_hits(build_full_stats, SESSION_HOURS, food_heal_pct,
                                       end_reserve_pct=SESSION_END_RESOURCE_PCT)
    phase = min(window_phase, session_phase, key=lambda p: p["max_hits"])
    return {"window": window, "phases": {"none": phase}, "total_max_hits": phase["max_hits"]}
