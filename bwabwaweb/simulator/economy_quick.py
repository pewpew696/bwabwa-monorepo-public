# simulator/economy_quick.py — ekonomi per-hari & quick sim

import logging

from simulator.constants import (
    AE_PP_PER_DAY,
    AMMO_MULTIPLIERS,
    AMMO_REF_PRICES,
    BASE_HEALTH_COST,
    BATTLE_BONUS_CAP_NORMAL,
    BATTLE_BONUS_CAP_REVOLT,
    BATTLE_LOOT_BONUS_CAP,
    BATTLE_LOOT_K_A,
    BATTLE_LOOT_K_B,
    DEFAULT_CASE_VALUE,
    DEFAULT_ELITE_CASE_VALUE,
    FOOD_ITEMS,
    HP_REGEN_PCT_PER_HOUR,
    HUNGER_REGEN_PCT_PER_HOUR,
    LOOT_ELITE_CASE_RATIO,
    MISS_DAMAGE_MULTIPLIER,
    PILL_BUFF_DURATION_HOURS,
    PILL_MULTIPLIERS,
    PILL_NEUTRAL_DURATION_HOURS,
    PRODUCTION_CHAIN,
    SCRAP_BASE,
    SCRAP_RECOVERY_RATIO,
    SESSION_END_RESOURCE_PCT,
    SESSION_HOURS,
    WINDOW_HOURS,
)

log = logging.getLogger("WarEraBot.economy_quick")


# --- cost helpers ---
def _craft_cost(rarity: str, market: dict) -> float:
    """Craft cost (scrap+steel di harga market live) untuk 1 item rarity tsb.
    Dipakai sebagai basis wear cost karena WarEra tidak punya mekanisme repair."""
    base = SCRAP_BASE.get(rarity, {"scrap": 0, "steel": 0})
    price_scrap = market.get("Scraps", 0) or 0
    price_steel = market.get("Steel", 0) or 0
    return base["scrap"] * price_scrap + base["steel"] * price_steel


def _calculate_equipment_wear_cost(durability_loss: dict, equipment: dict, market: dict) -> float:
    """Wear cost per-rarity dari durability_loss aktual (bukan proxy flat).
    durability_loss: {"weapon": -241, "helmet": -180, ...} (negatif = % durability hilang)
    equipment: {"weapon": {"rarity": "Ungu", ...}, ...}
    Advanced (builder Fase 7): slot boleh bawa "value" (gold eksplisit) sebagai
    pengganti craft cost rarity, dan "durability" < 100 (gear bekas) menurunkan
    nilai ekonomis proporsional kondisi. Simplified selalu durability=100 tanpa
    value -> perilaku lama tidak berubah."""
    equipment = equipment or {}
    total = 0.0
    for slot, loss_pct in durability_loss.items():
        wear_fraction = abs(loss_pct) / 100
        info = equipment.get(slot, {})
        value = info.get("value")
        basis = float(value) if value is not None else _craft_cost(
            info.get("rarity", "Putih"), market)
        durability_factor = (info.get("durability", 100) or 100) / 100
        total += wear_fraction * basis * durability_factor
    return total


# ============================================================
# 4. COMPANY INCOME (AE + Production Chain)
# ============================================================

def _calculate_company_income(econ: dict, market: dict) -> dict:
    """
    Hitung passive income dari company + AE + production chain.

    STATUS: 🔴 ASSUMPTION (per 2026-08-22) — mendukung company yang produksi
    item BERBEDA-BEDA (bukan cuma 1 item sama rata seperti versi lama), dan
    netting transfer internal (raw dari 1 company dipakai company lain tanpa
    lewat market). Belum divalidasi ke company list real (user sedang tidak
    dalam mode war saat desain ini dibuat) — validasi menyusul.

    Args:
        econ: {
            "companies": [
                {"ae_level": 6, "production_target": "Iron"},
                {"ae_level": 6, "production_target": "Steel"},
                ...
            ]
        }
        Kalau "companies" tidak diisi, fallback ke format lama
        (company_count + ae_levels + company_production, 1 item shared)
        untuk backward-compat dengan optimizer.py yang belum diupdate.
        production_target kosong per company -> default "Iron" (sesuai
        keputusan user: dipakai kalau data real belum bisa dicek).
        market: harga per item, idealnya dari cache realtime (price_history,
        Supabase project BwabwabwaBot — bot fetch tiap ±10-15 menit), bukan
        harga statis hardcoded.

    Returns: {
        "net_income": float,
        "breakdown": [{"ae_level", "production_target", "units_per_day",
                        "internal_transfer", "market_sold"/"market_bought"}, ...]
    }
    """
    companies = econ.get("companies")
    if not companies:
        # Backward-compat: format lama (1 item sama rata semua company)
        company_count = econ.get("company_count", 0)
        ae_levels = econ.get("ae_levels", [])
        production_target = econ.get("company_production") or "Iron"
        if not company_count:
            return {"net_income": 0.0, "breakdown": []}
        companies = [
            {"ae_level": ae_levels[i] if i < len(ae_levels) else 1,
             "production_target": production_target}
            for i in range(company_count)
        ]

    for c in companies:
        if not c.get("production_target"):
            c["production_target"] = "Iron"  # default sesuai keputusan user

    def _units_per_day(company: dict) -> int:
        prod = PRODUCTION_CHAIN.get(company["production_target"])
        if not prod or prod["pp"] <= 0:
            return 0
        pp = AE_PP_PER_DAY.get(company.get("ae_level", 1), 0)
        return pp // prod["pp"]

    # 1. Produksi kotor per item (gabungan semua company yang produksi item itu)
    gross_output = {}
    for c in companies:
        item = c["production_target"]
        if item not in PRODUCTION_CHAIN:
            continue
        gross_output[item] = gross_output.get(item, 0) + _units_per_day(c)

    # 2. Kebutuhan input internal per item (company yang produksi barang olahan)
    internal_need = {}
    for c in companies:
        prod = PRODUCTION_CHAIN.get(c["production_target"])
        if not prod or not prod["input"]:
            continue
        input_item, input_qty = prod["input"]
        internal_need[input_item] = internal_need.get(input_item, 0) + _units_per_day(c) * input_qty

    # 3. Netting: transfer internal = min(produksi, kebutuhan) per item, GRATIS (tidak lewat market)
    internal_transfer = {
        item: min(gross_output.get(item, 0), need)
        for item, need in internal_need.items()
    }

    # 4. Revenue: surplus (produksi - dipakai internal) dijual ke market
    revenue = 0.0
    for item, produced in gross_output.items():
        surplus = produced - internal_transfer.get(item, 0)
        revenue += surplus * market.get(item, 0)

    # 5. Cost: kekurangan (kebutuhan - dipenuhi internal) dibeli dari market
    cost = 0.0
    for item, need in internal_need.items():
        shortfall = need - internal_transfer.get(item, 0)
        cost += shortfall * market.get(item, 0)

    net_income = revenue - cost

    breakdown = []
    for c in companies:
        breakdown.append({
            "ae_level": c.get("ae_level", 1),
            "production_target": c["production_target"],
            "units_per_day": _units_per_day(c),
        })

    return {"net_income": round(net_income, 2), "breakdown": breakdown}


# --- quick simulate ---
def quick_simulate(stats: dict, battle_config: dict) -> dict:
    """
    Versi cepat: hitung EXPECTED damage & cost tanpa RNG loop.
    Cocok untuk UI builder yang mau real-time update saat slider diubah.

    Returns expected values (E[damage], E[hp_cost], dst.) — bukan hasil simulasi.
    """

    # ── Expected Damage per Hit ──
    ammo_mult = AMMO_MULTIPLIERS.get(battle_config.get("ammo_tier", "ammo"), 1.20)
    pill_mult = PILL_MULTIPLIERS.get(battle_config.get("pill_state", "none"), 1.00)
    rank_bonus_pct = battle_config.get("rank_bonus_pct", 0) / 100.0
    rank_mult = 1 + rank_bonus_pct

    personal_attack = stats["attack"] * ammo_mult * pill_mult * rank_mult

    bb_pct = battle_config.get("battle_bonus_pct", 0) / 100.0
    bb_cap = BATTLE_BONUS_CAP_REVOLT if battle_config.get("is_revolt") else BATTLE_BONUS_CAP_NORMAL
    bb_pct = min(bb_pct, bb_cap)
    bb_mult = 1 + bb_pct

    base_damage = personal_attack * bb_mult

    # E[damage] = P(hit) × (P(crit|hit) × crit_damage + P(no_crit|hit) × 1) × base
    #           + P(miss) × 0.5 × base
    p_hit = stats["precision_prob"]
    p_miss = 1 - p_hit
    p_crit_given_hit = stats["crit_chance_prob"]
    p_normal_given_hit = 1 - p_crit_given_hit

    crit_mult = 1 + stats["crit_dmg_mult"]

    e_damage = (
        p_hit * (p_crit_given_hit * crit_mult + p_normal_given_hit * 1.0) * base_damage
        + p_miss * MISS_DAMAGE_MULTIPLIER * base_damage
    )

    # ── Expected HP Cost per Hit ──
    p_dodge = stats["dodge_eff"]
    p_no_dodge = 1 - p_dodge
    e_hp_cost = p_no_dodge * (BASE_HEALTH_COST * (1 - stats["armor_eff"]))

    # ── Expected Loot per Hit ──
    loot_pct = stats["loot_chance_pct"] / 100.0
    e_case = loot_pct
    e_elite_case = loot_pct * LOOT_ELITE_CASE_RATIO

    return {
        "expected_damage_per_hit": e_damage,
        "expected_hp_cost_per_hit": e_hp_cost,
        "expected_crit_damage_per_hit": base_damage * crit_mult,
        "expected_normal_damage_per_hit": base_damage,
        "expected_miss_damage_per_hit": base_damage * MISS_DAMAGE_MULTIPLIER,
        "crit_chance": stats["crit_chance_prob"],
        "miss_chance": 1 - stats["precision_prob"],
        "dodge_chance": stats["dodge_eff"],
        "armor_effectiveness": stats["armor_eff"],
        "expected_case_per_hit": e_case,
        "expected_elite_case_per_hit": e_elite_case,
        "personal_attack": personal_attack,
        "battle_bonus_multiplier": bb_mult,
        "rank_mult": rank_mult,
        "ammo_mult": ammo_mult,
        "pill_mult": pill_mult,
        "ehp": stats["max_hp"] / e_hp_cost if e_hp_cost > 0 else float("inf"),
    }


# Presisi tampilan hasil quick_simulate (batas API); hitungan internal memakai nilai penuh.
SIM_DECIMALS = {
    "expected_damage_per_hit": 2,
    "expected_hp_cost_per_hit": 2,
    "expected_crit_damage_per_hit": 2,
    "expected_normal_damage_per_hit": 2,
    "expected_miss_damage_per_hit": 2,
    "crit_chance": 4,
    "miss_chance": 4,
    "dodge_chance": 4,
    "armor_effectiveness": 4,
    "expected_case_per_hit": 4,
    "expected_elite_case_per_hit": 6,
    "personal_attack": 2,
    "battle_bonus_multiplier": 4,
    "ehp": 2,
}


def round_sim(sim: dict) -> dict:
    """Salinan hasil quick_simulate dengan presisi tampilan; kunci lain tidak diubah."""
    return {key: round(value, SIM_DECIMALS[key]) if key in SIM_DECIMALS else value
            for key, value in sim.items()}


# --- ammo ---
def _needs_ammo(weapon_rarity: str, ammo_tier: str) -> bool:
    """Ammo terpakai kalau senjata bukan Putih (knife) dan tier bukan none/knife."""
    return weapon_rarity != "Putih" and ammo_tier not in ("none", "knife")


# --- food sisi hunger ---
def _hunger_food_per_day(max_hunger: float, hours: int, use_pill: bool,
                         hunger_cost: float) -> float:
    """Food/hari dari sisi hunger (model S2). Window 8/16/24 jam = jam pertama
    sesi 24 jam. Pill: buff 8 jam saja (8/16 jam), ditambah sisa hunger fase
    netral (24 jam); fase debuff tidak menambah food (regen terbuang di cap).
    Tanpa pill: burst di awal sesi, dicap total sesi 24 jam."""
    if hours not in WINDOW_HOURS.values():
        raise ValueError(f"hours harus salah satu dari {list(WINDOW_HOURS.values())}, dapat: {hours!r}")
    h = HUNGER_REGEN_PCT_PER_HOUR
    if use_pill:
        food = max_hunger * (1 + PILL_BUFF_DURATION_HOURS * h)
        if hours == SESSION_HOURS:
            food += max_hunger * (1 + PILL_NEUTRAL_DURATION_HOURS * h - SESSION_END_RESOURCE_PCT)
    else:
        food = max_hunger * min(1 + h * hours, 1 + SESSION_HOURS * h - SESSION_END_RESOURCE_PCT)
    return max(0.0, food / hunger_cost)


# --- food sisi HP (tanpa pill) ---
def _hp_food_per_day(hits: float, hp_cost: float, max_hp: float,
                     heal_pct: float, hours: int) -> float:
    """Food/hari dari sisi HP tanpa pill: HP terpakai dikurangi regen selama
    window dan (hanya window 24 jam) cadangan HP akhir sesi, dibagi HP per food."""
    if max_hp * heal_pct <= 0:
        return 0.0
    reserve = (1 - SESSION_END_RESOURCE_PCT) * max_hp if hours == SESSION_HOURS else 0
    needed = hits * hp_cost - HP_REGEN_PCT_PER_HOUR * max_hp * hours - reserve
    return max(0.0, needed / (max_hp * heal_pct))


# --- battle loot (F017, kalibrasi Fase 1) ---
def battle_loot_income(damage: float, battle_bonus_pct: float,
                       rank_bonus_pct: float) -> float:
    """Battle loot income dari damage: k x damage/1000.

    k = BATTLE_LOOT_K_A x battle_bonus x (1 + BATTLE_LOOT_K_B x rank_bonus),
    battle bonus dicap BATTLE_LOOT_BONUS_CAP. Fit empiris probe builder
    2026-10-08 — BUKAN bagian loot skill (itu case income), income line sendiri.
    Dipakai calculate_daily_projection() dan Build Optimizer (Monte Carlo).
    """
    bb = min(battle_bonus_pct, BATTLE_LOOT_BONUS_CAP)
    k = BATTLE_LOOT_K_A * bb * (1 + BATTLE_LOOT_K_B * rank_bonus_pct)
    return k * (damage / 1000)


# --- daily projection ---
def calculate_daily_projection(quick_sim: dict, stats: dict,
                               battle_config: dict, economy_config: dict,
                               hits_per_day: int = 300,
                               equipment: dict = None,
                               hours: int = SESSION_HOURS) -> dict:
    """
    Hitung daily projection dari expected per-hit values.
    Tidak perlu RNG loop — pakai expected values dari quick_simulate().

    Args:
        quick_sim: output dari quick_simulate()
        stats: output dari calculate_base_stats()
        battle_config: battle scenario config
        economy_config: economy config (market prices, food, companies)
        hits_per_day: jumlah hit per hari (default 300)
        equipment: {"weapon": {"rarity": ...}, "helmet": {...}, ...} — dipakai
            untuk hitung wear cost dari craft cost (scrap+steel) per slot,
            karena WarEra tidak punya mekanisme "repair" (lihat F011/F012).
        hours: window sesi 8/16/24 jam (8/16 = jam pertama sesi 24 jam), selain itu ValueError.
            Sisi HP (tanpa pill) memakai hits_per_day apa adanya: untuk 8/16 jam kirim hit dalam window itu.

    Returns: dict dengan daily damage, economy breakdown, gold per K.
    """
    equipment = equipment or {}
    e_dmg = quick_sim["expected_damage_per_hit"]
    e_hp_cost = quick_sim["expected_hp_cost_per_hit"]
    e_case = quick_sim["expected_case_per_hit"]
    e_elite = quick_sim["expected_elite_case_per_hit"]
    ehp = quick_sim["ehp"]

    # ── Daily Combat ──
    daily_damage = e_dmg * hits_per_day
    daily_hp_cost = e_hp_cost * hits_per_day

    # ── Food consumption ──
    food_type = economy_config.get("food_type", "Steak")
    if food_type in ("none", None):
        food_heal_pct = 0
    else:
        food_heal_pct = FOOD_ITEMS.get(food_type, FOOD_ITEMS["Steak"])["heal_pct"]

    # Food: sisi hunger; tanpa pill dibatasi juga sisi HP (nilai terkecil).
    # Mode pill sengaja beda dari Intel (16,0 vs 19): ikut perilaku pill owner
    # (lembar data 2026-10-08 bag. 7).
    hunger_cost = FOOD_ITEMS.get(food_type, FOOD_ITEMS["Steak"])["hunger_cost"]
    use_pill = battle_config.get("pill_state", "none") != "none"
    daily_food_eaten = _hunger_food_per_day(stats["max_hunger"], hours, use_pill, hunger_cost)
    if not use_pill and food_heal_pct > 0:
        daily_food_eaten = min(daily_food_eaten, _hp_food_per_day(
            hits_per_day, e_hp_cost, stats["max_hp"], food_heal_pct, hours))
    if food_heal_pct <= 0:
        daily_food_eaten = 0

    # ── Ammo consumption ──
    ammo_tier = battle_config.get("ammo_tier", "ammo")
    weapon_rarity = (equipment or {}).get("weapon", {}).get("rarity", "Hijau")
    needs_ammo = _needs_ammo(weapon_rarity, ammo_tier)
    daily_ammo_used = hits_per_day if needs_ammo else 0

    # ── Durability loss ──
    # Expected: (1 - dodge_eff) fraction of hits damage all 6 slots, dodge hits only weapon
    p_dodge = stats["dodge_eff"]
    p_no_dodge = 1 - p_dodge
    # Per hit: all slots lose 1% if not dodged, only weapon if dodged
    # Average durability loss per slot per hit:
    # weapon: always -1%, others: -1% * p_no_dodge
    daily_durability_weapon = hits_per_day * 1.0  # always -1%
    daily_durability_other = hits_per_day * p_no_dodge  # only when not dodged

    # ── Market prices ──
    market = economy_config.get("market_prices", {})

    # Ammo cost
    ammo_cost_day = 0
    if needs_ammo:
        ammo_item_name = {
            "light": "Light Ammo",
            "ammo": "Ammo",
            "heavy": "Heavy Ammo",
        }.get(ammo_tier, "Ammo")
        ammo_price = market.get(ammo_item_name, AMMO_REF_PRICES.get(ammo_item_name, {}).get("min", 0))
        ammo_cost_day = daily_ammo_used * ammo_price

    # Food cost
    food_cost_day = 0
    if food_type not in ("none", None):
        food_price = market.get(food_type, 10.0)
        food_cost_day = daily_food_eaten * food_price

    # Loot income (cases) — harga live "Case 1"/"Case 2" dari market cache, sama
    # pola dengan ammo/food (lihat komentar lengkap di simulate_session()).
    case_value = market.get("Case 1", economy_config.get("case_value", DEFAULT_CASE_VALUE))
    elite_case_value = market.get("Case 2", economy_config.get("elite_case_value", DEFAULT_ELITE_CASE_VALUE))
    daily_loot_income = (e_case * hits_per_day * case_value) + (e_elite * hits_per_day * elite_case_value)

    # Battle loot income — efek samping dealing damage (F017, probe builder 2026-10-08).
    # BUKAN bagian dari loot skill (itu case income di atas) — income line sendiri.
    daily_battle_loot_income = battle_loot_income(
        daily_damage,
        battle_config.get("battle_bonus_pct", 0),
        battle_config.get("rank_bonus_pct", 0),
    )

    # Company income (already per-day in _calculate_company_income)
    company_result = _calculate_company_income(economy_config, market)
    company_income_day = company_result["net_income"]
    company_breakdown = company_result["breakdown"]

    # Equipment wear cost — WarEra tidak punya mekanisme "repair" (F011/F012),
    # jadi wear cost dihitung dari craft cost (scrap+steel di harga market live)
    # per slot, diamortisasi per 1% durability yang habis (100% = 1 item baru).
    # BUGFIX (2026-08-22): formula lama membagi craft_cost dengan /100 KEDUA
    # KALINYA padahal wp_wear/slot_wear sudah mengonversi durability_%_hilang
    # jadi pecahan jumlah item (mis. 241% -> 2.41 item). Divalidasi terhadap
    # 2 sample WarEra Intel: build_1 cocok sampai +1.5% setelah fix ini
    # (sebelumnya -99%, wear cost nyaris nol). build_2 membaik dari -99% ke
    # -38% (sisa gap diduga dari ketidakpastian rarity gear per-slot, bukan
    # dari formula ini) -> status: 🟡 STRONG EVIDENCE, belum VERIFIED penuh.
    # Pakai _craft_cost() module-level yang sama dengan simulate_session().
    wear_cost_day = 0
    # Weapon: loses 1% per hit always
    wp_rarity = equipment.get("weapon", {}).get("rarity", "Putih")
    wp_wear = daily_durability_weapon / 100
    wear_cost_day += wp_wear * _craft_cost(wp_rarity, market)
    # Other slots: lose 1% per non-dodged hit
    for slot in ["helmet", "chest", "pants", "gloves", "boots"]:
        slot_rarity = equipment.get(slot, {}).get("rarity", "Putih")
        slot_wear = daily_durability_other / 100
        wear_cost_day += slot_wear * _craft_cost(slot_rarity, market)

    # Scrap income — recovery dari gear yang kekonsumsi di battle (F018, probe).
    # Builder: ~= 27.7% x gear durability cost, konstan lintas jam. Income line
    # pengurang (bukan potongan wear cost), ikut rumus builder.
    daily_scrap_income = wear_cost_day * SCRAP_RECOVERY_RATIO

    # ── Totals ──
    # Rumus builder (terverifikasi probe 2026-10-08):
    #   net = (gear_cost + consumables) - (scrap + cases + battle_loot + companies + work)
    # Work (wage/self-work/employee) belum dimodelkan engine — flag buat owner.
    total_costs_day = ammo_cost_day + food_cost_day + wear_cost_day
    total_income_day = (daily_loot_income + daily_battle_loot_income
                        + daily_scrap_income + company_income_day)
    net_profit_day = total_income_day - total_costs_day

    # Gold per K damage
    gold_per_k = (net_profit_day / (daily_damage / 1000)) if daily_damage > 0 else 0

    return {
        "hits_per_day": hits_per_day,
        # Combat
        "daily_damage": round(daily_damage, 2),
        "daily_hp_cost": round(daily_hp_cost, 2),
        "daily_food_eaten": round(daily_food_eaten, 1),
        "daily_ammo_used": daily_ammo_used,
        "ehp": round(ehp, 2),
        # Economy breakdown
        "daily_ammo_cost": round(ammo_cost_day, 2),
        "daily_food_cost": round(food_cost_day, 2),
        "daily_wear_cost": round(wear_cost_day, 2),
        "daily_loot_income": round(daily_loot_income, 2),
        "daily_battle_loot_income": round(daily_battle_loot_income, 2),
        "daily_scrap_income": round(daily_scrap_income, 2),
        "daily_company_income": round(company_income_day, 2),
        "company_breakdown": company_breakdown,  # [{"ae_level","production_target","units_per_day"}, ...]
        "daily_total_costs": round(total_costs_day, 2),
        "daily_total_income": round(total_income_day, 2),
        "daily_net_profit": round(net_profit_day, 2),
        "gold_per_k": round(gold_per_k, 4),
    }