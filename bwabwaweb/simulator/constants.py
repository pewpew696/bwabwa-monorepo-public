"""
WarEra Combat Simulator v2 — Game Constants
Semua data dari Project Bible v2.2 + koreksi empiris user.
Setiap section menulis source Formula Reference-nya.
"""

# ============================================================
# F001 — CHARACTER LEVEL & XP PROGRESSION
# ============================================================

CHAR_LEVEL_CAP = 50
SP_PER_LEVEL = 4          # flat, konstan
SP_STARTING = 4            # level 1 = 4 SP

def xp_required(current_level: int) -> int:
    """XP untuk naik dari current_level ke current_level+1."""
    if current_level < 0 or current_level >= CHAR_LEVEL_CAP:
        return 0
    if current_level <= 2:      # level 1→2, 2→3
        return 100
    elif current_level <= 5:    # level 3→4, 4→5, 5→6
        return 200
    else:                       # level 6+ : (N-4) × 100
        return (current_level - 4) * 100

# ============================================================
# F002 — SKILL POINT COST SYSTEM
# ============================================================

SKILL_MAX_LEVEL = 10
SP_COST_PER_LEVEL = lambda lvl: lvl          # cost(level) = level
SP_TOTAL_TO_MAX = 55                          # 10*(10+1)/2
SP_TOTAL_ALL_SKILLS = 715                     # 13 × 55
SP_PER_RESPEC_FREE = 2                        # gratis seumur hidup
RESPEC_COOLDOWN_DAYS = 7
RESPEC_PAID_GOLD_PCT = 0.50                   # 50% dari total SP

# Skill definitions: (key, name, category, effect_per_level, base, max, unlock_level)
# Keputusan owner 2026-10-08 (lembar data): konstanta kode dipertahankan,
# bukan nilai wiki. Attack +25/lv, armor +6/lv (poin, diminishing), health base 100.
SKILLS = {
    # ── Combat (8) ──
    "attack":       {"name": "Attack",       "cat": "combat",   "per_lvl": 25,  "base": 100,  "max": 350,  "unlock": 1},
    "precision":    {"name": "Precision",    "cat": "combat",   "per_lvl": 5,   "base": 50,   "max": 100,  "unlock": 1},   # % hit rate
    "crit_chance":  {"name": "Crit Chance",  "cat": "combat",   "per_lvl": 5,   "base": 10,   "max": 60,   "unlock": 5},   # %
    "crit_damage":  {"name": "Crit Damage",  "cat": "combat",   "per_lvl": 20,  "base": 100,  "max": 300,  "unlock": 10},  # % bonus
    "armor":        {"name": "Armor",        "cat": "combat",   "per_lvl": 6,   "base": 0,    "max": 60,   "unlock": 5},   # flat armor
    "dodge":        {"name": "Dodge",        "cat": "combat",   "per_lvl": 4,   "base": 0,    "max": 40,   "unlock": 10},  # flat dodge
    "health":       {"name": "Health",       "cat": "combat",   "per_lvl": 10,  "base": 100,  "max": 200,  "unlock": 5},   # max HP
    "hunger":       {"name": "Hunger",       "cat": "combat",   "per_lvl": 1,   "base": 4,    "max": 14,   "unlock": 5},   # max hunger

    # ── Economy (1, relevant untuk simulator) ──
    "companies":    {"name": "Companies",    "cat": "economy",  "per_lvl": 1,   "base": 2,    "max": 12,   "unlock": 1},

    # ── Special (1) ──
    "loot_chance":  {"name": "Loot Chance",  "cat": "special",  "per_lvl": 2,   "base": 5,    "max": 25,   "unlock": 10},  # %, scaling +2%/level
}

# Skills yang TIDAK masuk simulator (player strategy, non-combat)
SKILLS_EXCLUDED = ["energy", "entrepreneurship", "production", "management"]

# ============================================================
# F003 — ATTACK FORMULA
# ============================================================
# Attack = AttackSkill + WeaponAttack + PrecisionOverflow

# ============================================================
# F004 — PRECISION OVERFLOW
# ============================================================
PRECISION_CAP = 100           # hit rate di-cap 100%
PRECISION_OVERFLOW_MULT = 4   # setiap 1% overflow = +4 Attack

# ============================================================
# F005 — CRIT CHANCE OVERFLOW
# ============================================================
CRIT_CHANCE_CAP = 100         # crit chance di-cap 100%
CRIT_OVERFLOW_MULT = 0.04     # setiap 1% overflow = +4% Crit Damage

# ============================================================
# F006 — BUFF MULTIPLICATION
# ============================================================
# Pipeline: Attack × AmmoMult × PillMult × RankMult × BattleBonusMult

AMMO_MULTIPLIERS = {
    "none":  1.00,   # No ammo (Fix #4)
    "knife":  1.00,   # Putih weapon, no ammo
    "light":  1.10,   # +10%
    "ammo":   1.20,   # +20%
    "heavy":  1.40,   # +40%
}

PILL_MULTIPLIERS = {
    "none":   1.00,
    "buff":   1.60,   # +60% selama 8 jam
    "debuff": 0.40,   # -60% selama ~15.5 jam
}

# Sesi pemain 24 jam; window 8h/16h = jam pertama sesi itu (keputusan owner S2)
SESSION_HOURS = 24
WINDOW_HOURS = {"8h": 8, "16h": 16, "24h": SESSION_HOURS}

PILL_BUFF_DURATION_HOURS = 8.0
PILL_DEBUFF_DURATION_HOURS = 15.5
# fase none: sisa sesi setelah buff dan debuff
PILL_NEUTRAL_DURATION_HOURS = SESSION_HOURS - PILL_BUFF_DURATION_HOURS - PILL_DEBUFF_DURATION_HOURS

# ============================================================
# F007 — BATTLE BONUS
# ============================================================
BATTLE_BONUS_CAP_NORMAL = 0.95    # +95% (×1.95)
BATTLE_BONUS_CAP_REVOLT = 1.15    # +115% (×2.15)

# ============================================================
# F008 — ARMOR EFFECTIVENESS
# ============================================================
# ArmorEff = Armor / (Armor + 40)
ARMOR_EFFECTIVENESS_CAP = 0.90    # hard cap 90%
ARMOR_FORMULA_CONSTANT = 40

# ============================================================
# F009 — DODGE EFFECTIVENESS
# ============================================================
# DodgeEff = Dodge / (Dodge + 40)
DODGE_FORMULA_CONSTANT = 40

# ============================================================
# F010 — BASE HEALTH COST
# ============================================================
BASE_HEALTH_COST = 10             # per Combat Action, sebelum modifier

# ============================================================
# F016 — HP/HUNGER REGEN (Combat Bible v2.2, VERIFIED 3 sumber independen;
# "tetap jalan walau terus-menerus hit, ngikut jam dinding" — confirmed user
# 2026-09-03, bukan idle-only)
# ============================================================
HP_REGEN_PCT_PER_HOUR = 0.10        # 10% dari Max HP per jam
HUNGER_REGEN_PCT_PER_HOUR = 0.10    # 10% dari Max Hunger per jam
SESSION_END_RESOURCE_PCT = 0.85     # sisa HP/hunger di akhir sesi 24 jam (keputusan owner S2)

# ============================================================
# F011 — EQUIPMENT DURABILITY
# ============================================================
DURABILITY_LOSS_PER_HIT = 1       # % per slot equipment
EQUIPMENT_SLOTS = ["weapon", "helmet", "chest", "pants", "gloves", "boots"]
# Saat dodge: hanya weapon yang -1%, lainnya 0

# ============================================================
# F012 — SCRAP VALUE & DISMANTLE
# ============================================================
# Scrap = 6 × 3^(tier-1) di 100% durability
RARITY_TIER = {
    "Putih": 1, "Hijau": 2, "Biru": 3,
    "Ungu": 4, "Oren": 5, "Merah": 6,
}
RARITY_ORDER = ["Putih", "Hijau", "Biru", "Ungu", "Oren", "Merah"]

SCRAP_BASE = {
    "Putih":  {"scrap": 6,    "steel": 1},
    "Hijau":  {"scrap": 18,   "steel": 2},
    "Biru":   {"scrap": 54,   "steel": 4},
    "Ungu":   {"scrap": 162,  "steel": 8},
    "Oren":   {"scrap": 486,  "steel": 16},
    "Merah":  {"scrap": 1458, "steel": 32},
}

def scrap_yield(rarity: str, durability_pct: float) -> dict:
    """Scrap yield berdasarkan band durability (F012 §5.2)."""
    base = SCRAP_BASE.get(rarity, {"scrap": 0, "steel": 0})
    if durability_pct >= 100:    deduction = 0
    elif durability_pct >= 75:  deduction = 1
    elif durability_pct >= 50:  deduction = 2
    elif durability_pct >= 25:  deduction = 3
    else:                        deduction = 4
    return {
        "scrap": max(0, base["scrap"] - deduction),
        "steel": base["steel"],  # steel tidak diketahui berkurang
        "deduction": deduction,
    }

# ============================================================
# F013 — EQUIPMENT RARITY STAT RANGES (KOREKSI EMPIRIS)
# ============================================================
# Format: [rarity, min, max]
# Gap antar tier SENGAJA (game design)

RARITY_STAT_RANGES = {
    "weapon_atk": [
        ("Putih", 21, 40), ("Hijau", 50, 60), ("Biru", 71, 90),
        ("Ungu", 101, 130), ("Oren", 141, 170), ("Merah", 221, 300),
    ],
    "weapon_crit_chance": [
        ("Putih", 1, 5), ("Hijau", 6, 10), ("Biru", 11, 15),
        ("Ungu", 16, 20), ("Oren", 26, 35), ("Merah", 41, 50),
    ],
    "helmet_crit_dmg": [
        ("Putih", 1, 15), ("Hijau", 16, 30), ("Biru", 31, 50),
        ("Ungu", 71, 90), ("Oren", 91, 110), ("Merah", 121, 150),
    ],
    "armor": [  # Chest & Pants, per slot
        ("Putih", 1, 5), ("Hijau", 6, 10), ("Biru", 11, 15),
        ("Ungu", 21, 30), ("Oren", 36, 50), ("Merah", 56, 70),
    ],
    "dodge": [  # Boots
        ("Putih", 1, 5), ("Hijau", 6, 10), ("Biru", 11, 15),
        ("Ungu", 21, 25), ("Oren", 26, 40), ("Merah", 51, 60),
    ],
    "precision": [  # Gloves
        ("Putih", 1, 5), ("Hijau", 6, 10), ("Biru", 11, 15),
        ("Ungu", 21, 25), ("Oren", 31, 40), ("Merah", 51, 60),
    ],
}

# Cap Gabungan Resmi per slot (F013 §5.6)
CAP_GABUNGAN_RESMI = {
    "weapon_atk":          300,
    "weapon_crit_chance":  50,   # %
    "helmet_crit_dmg":     150,  # %
    "armor_per_slot":      70,   # per slot (chest/pants)
    "dodge":               60,   # boots
    "precision":           60,   # gloves
}

# Map slot → stat types
SLOT_STAT_MAP = {
    "weapon":  ["weapon_atk", "weapon_crit_chance"],
    "helmet":  ["helmet_crit_dmg"],
    "chest":   ["armor"],
    "pants":   ["armor"],
    "boots":   ["dodge"],
    "gloves":  ["precision"],
}

# ============================================================
# F014 — LOOT CHANCE
# ============================================================
LOOT_ELITE_CASE_RATIO = 0.01   # 1% → 0.01% Elite Case per hit

# Harga case bawaan kalau "Case 1"/"Case 2" tidak ada di market live (user-confirmed 2026-08-28)
DEFAULT_CASE_VALUE = 3.6
DEFAULT_ELITE_CASE_VALUE = 22.5

# ============================================================
# F017 — BATTLE LOOT INCOME (probe Warera Build Tool 2026-10-08, EMPIRIS)
# ============================================================
# Builder (intel.warera.wiki/builder, mode SOLDIER manual): battle loot BUKAN
# konstanta — income per 1K damage (k) naik dengan battle bonus & rank bonus.
# Fit dari 6 titik probe (bonus, rank_bonus_pct) -> k:
#   (0,20)->0 | (50,20)->0.0451 | (60,20)->0.0533 | (100,20)->0.0838
#   (60,30)->0.0638 | (60,40)->0.0740
# Model: k = A * battle_bonus_pct * (1 + B * rank_bonus_pct).
# Residual max +6% di titik (100,20); sisanya <=1.5%. Status: EMPIRIS-dari-probe,
# bukan formula resmi game.
# ANOMALI TERBUKA: loot tidak skala linear dengan combat hours di builder
# (0.00 di 9h; 5.66 di 24h vs 2.42 di 18h). Engine memodelkan loot proporsional
# damage (sesuai deskripsi builder: "earned as a side effect of dealing damage")
# — perilaku jam builder belum bisa direproduksi, flag buat owner.
# CATATAN: 2 screenshot WarEra Intel lama memberi k ~0.171/K (3.2x probe) —
# diduga nerf balance di versi game baru (builder "updated for 0.25.4").
BATTLE_LOOT_K_A = 0.0005433
BATTLE_LOOT_K_B = 0.03175
BATTLE_LOOT_BONUS_CAP = 135.0  # max slider battle bonus di builder (probe)

# ============================================================
# F018 — SCRAP RECOVERY (probe Warera Build Tool 2026-10-08, EMPIRIS)
# ============================================================
# Builder: scrap_income ~= 27.7% x gear durability cost, konstan lintas jam
# (probe 0.2754-0.2778; tier Biru 0.2992). Screenshot Intel lama konsisten
# (24.5% & 27.8%). Dimodelkan sebagai income line pengurang, bukan potongan
# wear cost — ikut rumus builder: net = (gear+consumables) - (scrap+cases+loot+...).
SCRAP_RECOVERY_RATIO = 0.277

# ============================================================
# F015 — COMBAT EXECUTION PIPELINE
# ============================================================
# Miss takes priority over Crit (VERIFIED F015 v1.3.0)
# Miss → 50% damage, no crit (F014 evidence #6)
MISS_DAMAGE_MULTIPLIER = 0.50

# ============================================================
# MILITARY RANK TABLE (121 entries, Level 0-120)
# ============================================================

MILITARY_RANKS = [
    # --- BRONZE (Lv 0–48) ---
    {"lvl": 0,   "name": "Initiate",         "bonus": 0.00,  "mult": 1.0000, "dmg_req": 0},
    {"lvl": 1,   "name": "1☆ Initiate",     "bonus": 0.25,  "mult": 1.0025, "dmg_req": 500},
    {"lvl": 2,   "name": "2☆ Initiate",     "bonus": 0.50,  "mult": 1.0050, "dmg_req": 1000},
    {"lvl": 3,   "name": "3☆ Initiate",     "bonus": 0.75,  "mult": 1.0075, "dmg_req": 2000},
    # Level 4 — SKIPPED
    {"lvl": 5,   "name": "Trainee",          "bonus": 1.25,  "mult": 1.0125, "dmg_req": 4000},
    {"lvl": 6,   "name": "1☆ Trainee",      "bonus": 1.50,  "mult": 1.0150, "dmg_req": 5000},
    {"lvl": 7,   "name": "2☆ Trainee",      "bonus": 1.75,  "mult": 1.0175, "dmg_req": 6000},
    {"lvl": 8,   "name": "3☆ Trainee",      "bonus": 2.00,  "mult": 1.0200, "dmg_req": 8000},
    {"lvl": 9,   "name": "Recruit",          "bonus": 2.50,  "mult": 1.0250, "dmg_req": 10000},
    {"lvl": 10,  "name": "1☆ Recruit",      "bonus": 2.75,  "mult": 1.0275, "dmg_req": 11400},
    {"lvl": 11,  "name": "2☆ Recruit",      "bonus": 3.00,  "mult": 1.0300, "dmg_req": 12700},
    {"lvl": 12,  "name": "3☆ Recruit",      "bonus": 3.25,  "mult": 1.0325, "dmg_req": 15300},
    {"lvl": 13,  "name": "Cadet",            "bonus": 3.75,  "mult": 1.0375, "dmg_req": 18000},
    {"lvl": 14,  "name": "1☆ Cadet",        "bonus": 4.00,  "mult": 1.0400, "dmg_req": 20400},
    {"lvl": 15,  "name": "2☆ Cadet",        "bonus": 4.25,  "mult": 1.0425, "dmg_req": 22700},
    {"lvl": 16,  "name": "3☆ Cadet",        "bonus": 4.50,  "mult": 1.0450, "dmg_req": 27300},
    {"lvl": 17,  "name": "Private",          "bonus": 5.00,  "mult": 1.0500, "dmg_req": 32000},
    {"lvl": 18,  "name": "1☆ Private",      "bonus": 5.25,  "mult": 1.0525, "dmg_req": 35000},
    {"lvl": 19,  "name": "2☆ Private",      "bonus": 5.50,  "mult": 1.0550, "dmg_req": 38000},
    {"lvl": 20,  "name": "3☆ Private",      "bonus": 5.75,  "mult": 1.0575, "dmg_req": 44000},
    {"lvl": 21,  "name": "Trooper",          "bonus": 6.25,  "mult": 1.0625, "dmg_req": 50000},
    {"lvl": 22,  "name": "1☆ Trooper",      "bonus": 6.50,  "mult": 1.0650, "dmg_req": 55000},
    {"lvl": 23,  "name": "2☆ Trooper",      "bonus": 6.75,  "mult": 1.0675, "dmg_req": 60000},
    {"lvl": 24,  "name": "3☆ Trooper",      "bonus": 7.00,  "mult": 1.0700, "dmg_req": 70000},
    {"lvl": 25,  "name": "Specialist",       "bonus": 7.50,  "mult": 1.0750, "dmg_req": 80000},
    {"lvl": 26,  "name": "1☆ Specialist",   "bonus": 7.75,  "mult": 1.0775, "dmg_req": 87500},
    {"lvl": 27,  "name": "2☆ Specialist",   "bonus": 8.00,  "mult": 1.0800, "dmg_req": 95000},
    {"lvl": 28,  "name": "3☆ Specialist",   "bonus": 8.25,  "mult": 1.0825, "dmg_req": 110000},
    {"lvl": 29,  "name": "Corporal",         "bonus": 8.75,  "mult": 1.0875, "dmg_req": 125000},
    {"lvl": 30,  "name": "1☆ Corporal",     "bonus": 9.00,  "mult": 1.0900, "dmg_req": 138000},
    {"lvl": 31,  "name": "2☆ Corporal",     "bonus": 9.25,  "mult": 1.0925, "dmg_req": 150000},
    {"lvl": 32,  "name": "3☆ Corporal",     "bonus": 9.50,  "mult": 1.0950, "dmg_req": 175000},
    {"lvl": 33,  "name": "Sergeant",         "bonus": 10.00, "mult": 1.1000, "dmg_req": 200000},
    {"lvl": 34,  "name": "1☆ Sergeant",     "bonus": 10.25, "mult": 1.1025, "dmg_req": 217000},
    {"lvl": 35,  "name": "2☆ Sergeant",     "bonus": 10.50, "mult": 1.1050, "dmg_req": 234000},
    {"lvl": 36,  "name": "3☆ Sergeant",     "bonus": 10.75, "mult": 1.1075, "dmg_req": 267000},
    {"lvl": 37,  "name": "Vanguard",         "bonus": 11.25, "mult": 1.1125, "dmg_req": 300000},
    {"lvl": 38,  "name": "1☆ Vanguard",     "bonus": 11.50, "mult": 1.1150, "dmg_req": 325000},
    {"lvl": 39,  "name": "2☆ Vanguard",     "bonus": 11.75, "mult": 1.1175, "dmg_req": 350000},
    {"lvl": 40,  "name": "3☆ Vanguard",     "bonus": 12.00, "mult": 1.1200, "dmg_req": 400000},
    {"lvl": 41,  "name": "Operative",        "bonus": 12.50, "mult": 1.1250, "dmg_req": 450000},
    {"lvl": 42,  "name": "1☆ Operative",    "bonus": 12.75, "mult": 1.1275, "dmg_req": 487000},
    {"lvl": 43,  "name": "2☆ Operative",    "bonus": 13.00, "mult": 1.1300, "dmg_req": 529000},
    {"lvl": 44,  "name": "3☆ Operative",    "bonus": 13.25, "mult": 1.1325, "dmg_req": 597000},
    {"lvl": 45,  "name": "Petty Officer",    "bonus": 13.75, "mult": 1.1375, "dmg_req": 670000},
    {"lvl": 46,  "name": "1☆ Petty Officer","bonus": 14.00, "mult": 1.1400, "dmg_req": 725000},
    {"lvl": 47,  "name": "2☆ Petty Officer","bonus": 14.25, "mult": 1.1425, "dmg_req": 780000},
    {"lvl": 48,  "name": "3☆ Petty Officer","bonus": 14.50, "mult": 1.1450, "dmg_req": 890000},
    # --- SILVER (Lv 49–92) ---
    {"lvl": 49,  "name": "Chief",            "bonus": 15.00, "mult": 1.1500, "dmg_req": 1000000},
    {"lvl": 50,  "name": "1☆ Chief",        "bonus": 15.25, "mult": 1.1525, "dmg_req": 1090000},
    {"lvl": 51,  "name": "2☆ Chief",        "bonus": 15.50, "mult": 1.1550, "dmg_req": 1170000},
    {"lvl": 52,  "name": "3☆ Chief",        "bonus": 15.75, "mult": 1.1575, "dmg_req": 1330000},
    {"lvl": 53,  "name": "Warrant Officer",  "bonus": 16.25, "mult": 1.1625, "dmg_req": 1500000},
    {"lvl": 54,  "name": "1☆ Warrant Officer","bonus": 16.50, "mult": 1.1650, "dmg_req": 1630000},
    {"lvl": 55,  "name": "2☆ Warrant Officer","bonus": 16.75, "mult": 1.1675, "dmg_req": 1750000},
    {"lvl": 56,  "name": "3☆ Warrant Officer","bonus": 17.00, "mult": 1.1700, "dmg_req": 1990000},
    {"lvl": 57,  "name": "Ensign",           "bonus": 17.50, "mult": 1.1750, "dmg_req": 2230000},
    {"lvl": 58,  "name": "1☆ Ensign",       "bonus": 17.75, "mult": 1.1775, "dmg_req": 2430000},
    {"lvl": 59,  "name": "2☆ Ensign",       "bonus": 18.00, "mult": 1.1800, "dmg_req": 2620000},
    {"lvl": 60,  "name": "3☆ Ensign",       "bonus": 18.25, "mult": 1.1825, "dmg_req": 3010000},
    {"lvl": 61,  "name": "Lieutenant",       "bonus": 18.75, "mult": 1.1875, "dmg_req": 3400000},
    {"lvl": 62,  "name": "1☆ Lieutenant",   "bonus": 19.00, "mult": 1.1900, "dmg_req": 3670000},
    {"lvl": 63,  "name": "2☆ Lieutenant",   "bonus": 19.25, "mult": 1.1925, "dmg_req": 3940000},
    {"lvl": 64,  "name": "3☆ Lieutenant",   "bonus": 19.50, "mult": 1.1950, "dmg_req": 4470000},
    {"lvl": 65,  "name": "Captain",          "bonus": 20.00, "mult": 1.2000, "dmg_req": 5000000},
    {"lvl": 66,  "name": "1☆ Captain",       "bonus": 20.25, "mult": 1.2025, "dmg_req": 5450000},
    {"lvl": 67,  "name": "2☆ Captain",      "bonus": 20.50, "mult": 1.2050, "dmg_req": 5900000},
    {"lvl": 68,  "name": "3☆ Captain",      "bonus": 20.75, "mult": 1.2075, "dmg_req": 6800000},
    {"lvl": 69,  "name": "Major",            "bonus": 21.25, "mult": 1.2125, "dmg_req": 7700000},
    {"lvl": 70,  "name": "1☆ Major",        "bonus": 21.50, "mult": 1.2150, "dmg_req": 8330000},
    {"lvl": 71,  "name": "2☆ Major",        "bonus": 21.75, "mult": 1.2175, "dmg_req": 8950000},
    {"lvl": 72,  "name": "3☆ Major",        "bonus": 22.00, "mult": 1.2200, "dmg_req": 10200000},
    {"lvl": 73,  "name": "Lt. Colonel",      "bonus": 22.50, "mult": 1.2250, "dmg_req": 11500000},
    {"lvl": 74,  "name": "1☆ Lt. Colonel",  "bonus": 22.75, "mult": 1.2275, "dmg_req": 12500000},
    {"lvl": 75,  "name": "2☆ Lt. Colonel",  "bonus": 23.00, "mult": 1.2300, "dmg_req": 13400000},
    {"lvl": 76,  "name": "3☆ Lt. Colonel",  "bonus": 23.25, "mult": 1.2325, "dmg_req": 15200000},
    {"lvl": 77,  "name": "Colonel",          "bonus": 23.75, "mult": 1.2375, "dmg_req": 17000000},
    {"lvl": 78,  "name": "1☆ Colonel",      "bonus": 24.00, "mult": 1.2400, "dmg_req": 18500000},
    {"lvl": 79,  "name": "2☆ Colonel",      "bonus": 24.25, "mult": 1.2425, "dmg_req": 20000000},
    {"lvl": 80,  "name": "3☆ Colonel",      "bonus": 24.50, "mult": 1.2450, "dmg_req": 23000000},
    {"lvl": 81,  "name": "Brigadier",        "bonus": 25.00, "mult": 1.2500, "dmg_req": 26000000},
    {"lvl": 82,  "name": "1☆ Brigadier",    "bonus": 25.25, "mult": 1.2525, "dmg_req": 28200000},
    {"lvl": 83,  "name": "2☆ Brigadier",    "bonus": 25.50, "mult": 1.2550, "dmg_req": 30400000},
    {"lvl": 84,  "name": "3☆ Brigadier",     "bonus": 25.75, "mult": 1.2575, "dmg_req": 34700000},
    {"lvl": 85,  "name": "Commodore",        "bonus": 26.25, "mult": 1.2625, "dmg_req": 39000000},
    {"lvl": 86,  "name": "1☆ Commodore",    "bonus": 26.50, "mult": 1.2650, "dmg_req": 42200000},
    {"lvl": 87,  "name": "2☆ Commodore",    "bonus": 26.75, "mult": 1.2675, "dmg_req": 45400000},
    {"lvl": 88,  "name": "3☆ Commodore",     "bonus": 27.00, "mult": 1.2700, "dmg_req": 51700000},
    {"lvl": 89,  "name": "Marshal",          "bonus": 27.50, "mult": 1.2750, "dmg_req": 58000000},
    {"lvl": 90,  "name": "1☆ Marshal",      "bonus": 27.75, "mult": 1.2775, "dmg_req": 65000000},
    {"lvl": 91,  "name": "2☆ Marshal",      "bonus": 28.00, "mult": 1.2800, "dmg_req": 72000000},
    {"lvl": 92,  "name": "3☆ Marshal",      "bonus": 28.25, "mult": 1.2825, "dmg_req": 86000000},
    # --- GOLD (Lv 93–120) ---
    {"lvl": 93,  "name": "Rear Admiral",      "bonus": 28.75, "mult": 1.2875, "dmg_req": 100000000},
    {"lvl": 94,  "name": "1☆ Rear Admiral",  "bonus": 29.00, "mult": 1.2900, "dmg_req": 114000000},
    {"lvl": 95,  "name": "2☆ Rear Admiral",  "bonus": 29.25, "mult": 1.2925, "dmg_req": 127000000},
    {"lvl": 96,  "name": "3☆ Rear Admiral",   "bonus": 29.50, "mult": 1.2950, "dmg_req": 153000000},
    {"lvl": 97,  "name": "Vice Admiral",      "bonus": 30.00, "mult": 1.3000, "dmg_req": 180000000},
    {"lvl": 98,  "name": "1☆ Vice Admiral",  "bonus": 30.25, "mult": 1.3025, "dmg_req": 217000000},
    {"lvl": 99,  "name": "2☆ Vice Admiral",  "bonus": 30.50, "mult": 1.3050, "dmg_req": 254000000},
    {"lvl": 100, "name": "3☆ Vice Admiral",   "bonus": 30.75, "mult": 1.3075, "dmg_req": 327000000},
    {"lvl": 101, "name": "Admiral",           "bonus": 31.25, "mult": 1.3125, "dmg_req": 400000000},
    {"lvl": 102, "name": "1☆ Admiral",       "bonus": 31.50, "mult": 1.3150, "dmg_req": 445000000},
    {"lvl": 103, "name": "2☆ Admiral",       "bonus": 31.75, "mult": 1.3175, "dmg_req": 489000000},
    {"lvl": 104, "name": "3☆ Admiral",       "bonus": 32.00, "mult": 1.3200, "dmg_req": 577000000},
    {"lvl": 105, "name": "Lt. General",       "bonus": 32.50, "mult": 1.3250, "dmg_req": 666000000},
    {"lvl": 106, "name": "1☆ Lt. General",   "bonus": 32.75, "mult": 1.3275, "dmg_req": 694000000},
    {"lvl": 107, "name": "2☆ Lt. General",   "bonus": 33.00, "mult": 1.3300, "dmg_req": 722000000},
    {"lvl": 108, "name": "3☆ Lt. General",   "bonus": 33.25, "mult": 1.3325, "dmg_req": 767000000},
    {"lvl": 109, "name": "4☆ Lt. General",   "bonus": 33.50, "mult": 1.3350, "dmg_req": 833000000},
    {"lvl": 110, "name": "5☆ Lt. General",   "bonus": 33.75, "mult": 1.3375, "dmg_req": 917000000},
    {"lvl": 111, "name": "General",           "bonus": 34.25, "mult": 1.3425, "dmg_req": 1000000000},
    {"lvl": 112, "name": "1☆ General",       "bonus": 34.50, "mult": 1.3450, "dmg_req": 1090000000},
    {"lvl": 113, "name": "2☆ General",       "bonus": 34.75, "mult": 1.3475, "dmg_req": 1170000000},
    {"lvl": 114, "name": "3☆ General",       "bonus": 35.00, "mult": 1.3500, "dmg_req": 1300000000},
    {"lvl": 115, "name": "4☆ General",       "bonus": 35.25, "mult": 1.3525, "dmg_req": 1500000000},
    {"lvl": 116, "name": "5☆ General",       "bonus": 35.50, "mult": 1.3550, "dmg_req": 1750000000},
    {"lvl": 117, "name": "Commander",         "bonus": 36.00, "mult": 1.3600, "dmg_req": 2000000000},
    {"lvl": 118, "name": "High Commander",    "bonus": 36.50, "mult": 1.3650, "dmg_req": 3000000000},
    {"lvl": 119, "name": "Chief Commander",   "bonus": 37.00, "mult": 1.3700, "dmg_req": 5000000000},
    {"lvl": 120, "name": "Supreme Commander", "bonus": 37.50, "mult": 1.3750, "dmg_req": 10000000000},
]

def get_rank(level: int) -> dict | None:
    if level == 4 or level < 0 or level > 120:
        return None
    return next((r for r in MILITARY_RANKS if r["lvl"] == level), None)

# ============================================================
# ECONOMY — AE, PRODUCTION CHAIN, FOOD, AMMO PRICES
# ============================================================

# AE (Auto Engine) levels: PP per day = 24 × level
AE_PP_PER_DAY = {1: 24, 2: 48, 3: 72, 4: 96, 5: 120, 6: 144, 7: 168}

# PRODUCTION_CHAIN & ITEM_NOT_PRODUCIBLE pindah ke services/economy/constants.py (session 27 Sep).
# Re-export biar `from simulator.constants import *` tetap expose nama ini.
from services.economy.constants import ITEM_NOT_PRODUCIBLE, PRODUCTION_CHAIN  # noqa: E402,F401

# Food items: heal % of Max HP
FOOD_ITEMS = {
    "Bread":       {"heal_pct": 0.10, "hunger_cost": 1},
    "Steak":       {"heal_pct": 0.15, "hunger_cost": 1},
    "Cooked Fish": {"heal_pct": 0.20, "hunger_cost": 1},
}

# Ammo reference prices (fallback kalau API unavailable)
AMMO_REF_PRICES = {
    "Light Ammo": {"min": 0.15, "max": 0.25},
    "Ammo":       {"min": 0.70, "max": 0.75},
    "Heavy Ammo": {"min": 2.60, "max": 2.80},
}

# ============================================================
# HELPERS
# ============================================================

def get_stat_range(stat_type: str, rarity: str) -> tuple[int, int] | None:
    """Ambil (min, max) untuk stat type & rarity."""
    ranges = RARITY_STAT_RANGES.get(stat_type, [])
    for r, mn, mx in ranges:
        if r == rarity:
            return (mn, mx)
    return None

def get_skill_value(skill_key: str, level: int) -> float:
    """Hitung nilai skill pada level tertentu."""
    s = SKILLS[skill_key]
    return s["base"] + (s["per_lvl"] * level)

def total_sp_for_allocation(allocation: dict[str, int]) -> int:
    """Hitung total SP yang dibutuhkan untuk alokasi skill tertentu."""
    total = 0
    for skill_key, level in allocation.items():
        # SP cost untuk mencapai level N = N*(N+1)/2
        total += level * (level + 1) // 2
    return total

def max_sp_at_char_level(char_level: int) -> int:
    """Total SP yang dimiliki pemain pada character level tertentu."""
    return SP_PER_LEVEL * char_level