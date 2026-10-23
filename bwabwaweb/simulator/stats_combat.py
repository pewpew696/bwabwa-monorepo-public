# simulator/stats_combat.py — hitung base stats & satu aksi combat

import logging
import random

from simulator.constants import (
    AMMO_MULTIPLIERS,
    ARMOR_EFFECTIVENESS_CAP,
    ARMOR_FORMULA_CONSTANT,
    BASE_HEALTH_COST,
    BATTLE_BONUS_CAP_NORMAL,
    BATTLE_BONUS_CAP_REVOLT,
    CRIT_CHANCE_CAP,
    CRIT_OVERFLOW_MULT,
    DODGE_FORMULA_CONSTANT,
    EQUIPMENT_SLOTS,
    LOOT_ELITE_CASE_RATIO,
    MISS_DAMAGE_MULTIPLIER,
    PILL_MULTIPLIERS,
    PRECISION_CAP,
    PRECISION_OVERFLOW_MULT,
    SKILLS,
)

log = logging.getLogger("WarEraBot.stats_combat")


# --- base stats ---
def calculate_base_stats(skills: dict, equipment: dict, char_level: int) -> dict:
    """
    Hitung total stat pemain dari skill + equipment + overflow.

    Args:
        skills: {"attack": 5, "precision": 10, ...}  (0-10 per skill)
        equipment: {
            "weapon":  {"rarity": "Ungu", "stats": {"weapon_atk": 122, "weapon_crit_chance": 19}, "durability": 100},
            "helmet":  {"rarity": "Biru", "stats": {"helmet_crit_dmg": 40}, "durability": 80},
            "chest":   {"rarity": "Ungu", "stats": {"armor": 26}, "durability": 90},
            "pants":   {"rarity": "Ungu", "stats": {"armor": 26}, "durability": 90},
            "boots":   {"rarity": "Ungu", "stats": {"dodge": 22}, "durability": 100},
            "gloves":  {"rarity": "Oren","stats": {"precision": 35}, "durability": 100},
        }
        char_level: 1-50

    Returns: dict dengan semua stat final siap pakai untuk combat.
    """

    # ── 1. Skill base values (F002) ──
    attack_skill = SKILLS["attack"]["base"] + SKILLS["attack"]["per_lvl"] * skills.get("attack", 0)
    precision_skill = SKILLS["precision"]["base"] + SKILLS["precision"]["per_lvl"] * skills.get("precision", 0)
    crit_chance_skill = SKILLS["crit_chance"]["base"] + SKILLS["crit_chance"]["per_lvl"] * skills.get("crit_chance", 0)
    crit_dmg_skill = SKILLS["crit_damage"]["base"] + SKILLS["crit_damage"]["per_lvl"] * skills.get("crit_damage", 0)
    armor_skill = SKILLS["armor"]["per_lvl"] * skills.get("armor", 0)
    dodge_skill = SKILLS["dodge"]["per_lvl"] * skills.get("dodge", 0)
    max_hp = SKILLS["health"]["base"] + SKILLS["health"]["per_lvl"] * skills.get("health", 0)
    max_hunger = SKILLS["hunger"]["base"] + SKILLS["hunger"]["per_lvl"] * skills.get("hunger", 0)
    loot_chance = SKILLS["loot_chance"]["base"] + SKILLS["loot_chance"]["per_lvl"] * skills.get("loot_chance", 0)

    # ── 2. Equipment stats (F013) ──
    weapon = equipment.get("weapon", {})
    helmet = equipment.get("helmet", {})
    chest = equipment.get("chest", {})
    pants = equipment.get("pants", {})
    boots = equipment.get("boots", {})
    gloves = equipment.get("gloves", {})

    wp_atk = weapon.get("stats", {}).get("weapon_atk", 0)
    wp_crit = weapon.get("stats", {}).get("weapon_crit_chance", 0)
    helm_crit_dmg = helmet.get("stats", {}).get("helmet_crit_dmg", 0)
    chest_armor = chest.get("stats", {}).get("armor", 0)
    pants_armor = pants.get("stats", {}).get("armor", 0)
    boots_dodge = boots.get("stats", {}).get("dodge", 0)
    gloves_prec = gloves.get("stats", {}).get("precision", 0)

    # ── 3. Combine skill + equipment (F015: gabung dulu sebelum overflow) ──
    total_precision = precision_skill + gloves_prec       # % value
    total_crit_chance = crit_chance_skill + wp_crit       # % value
    total_crit_dmg_raw = crit_dmg_skill + helm_crit_dmg   # % value
    total_armor = armor_skill + chest_armor + pants_armor # flat value
    total_dodge = dodge_skill + boots_dodge               # flat value

    # ── 4. Precision Overflow (F004) ──
    # Precision > 100 → kelebihan × 4 = bonus Attack
    precision_overflow = max(0, total_precision - PRECISION_CAP)
    bonus_atk_overflow = precision_overflow * PRECISION_OVERFLOW_MULT

    # ── 5. Crit Chance Overflow (F005) ──
    # CritChance > 100% → kelebihan × 4% = bonus Crit Damage
    crit_overflow = max(0, total_crit_chance - CRIT_CHANCE_CAP)
    bonus_crit_dmg_overflow = crit_overflow * CRIT_OVERFLOW_MULT  # dalam % (e.g., 0.72 = 72%)

    # ── 6. Final Attack (F003) ──
    # Attack = AttackSkill + WeaponAttack + PrecisionOverflow
    final_attack = attack_skill + wp_atk + bonus_atk_overflow

    # ── 7. Final Crit Damage ──
    # Total crit dmg % = skill + equipment + overflow
    # Sebagai multiplier: 100% = 1.0 (crit deals 2× base), 300% = 3.0 (crit deals 4× base)
    final_crit_dmg_pct = total_crit_dmg_raw + bonus_crit_dmg_overflow
    final_crit_dmg_mult = final_crit_dmg_pct / 100.0  # e.g., 150% → 1.5

    # ── 8. Cap hit rate & crit chance (F004, F005) ──
    precision_prob = min(1.0, total_precision / 100.0)  # hit rate, capped 100%
    crit_chance_prob = min(1.0, total_crit_chance / 100.0)  # crit rate, capped 100%

    # ── 9. Armor Effectiveness (F008) ──
    # ArmorEff = Armor / (Armor + 40), hard cap 90%
    # (keputusan owner 2026-10-08: poin skill masuk diminishing, bukan flat %)
    armor_eff = total_armor / (total_armor + ARMOR_FORMULA_CONSTANT)
    armor_eff = min(armor_eff, ARMOR_EFFECTIVENESS_CAP)

    # ── 10. Dodge Effectiveness (F009) ──
    # DodgeEff = Dodge / (Dodge + 40), tanpa cap
    dodge_eff = total_dodge / (total_dodge + DODGE_FORMULA_CONSTANT)

    return {
        "attack": final_attack,
        "precision_prob": precision_prob,
        "crit_chance_prob": crit_chance_prob,
        "crit_dmg_mult": final_crit_dmg_mult,
        "armor_raw": total_armor,
        "armor_eff": armor_eff,
        "dodge_raw": total_dodge,
        "dodge_eff": dodge_eff,
        "max_hp": max_hp,
        "max_hunger": max_hunger,
        "loot_chance_pct": loot_chance,  # 5-25
        # Raw breakdown untuk display
        "_breakdown": {
            "attack_skill": attack_skill,
            "weapon_atk": wp_atk,
            "precision_overflow_atk": bonus_atk_overflow,
            "precision_total": total_precision,
            "crit_chance_total": total_crit_chance,
            "crit_dmg_total_pct": final_crit_dmg_pct,
            "armor_total": total_armor,
            "dodge_total": total_dodge,
        }
    }


# --- combat action ---
def execute_combat_action(stats: dict, battle_config: dict) -> dict:
    """
    Eksekusi 1 Combat Action (1 hit). Menghasilkan Damage Path + Resource Cost Path.

    Args:
        stats: output dari calculate_base_stats()
        battle_config: {
            "ammo_tier": "heavy",        # "knife"|"light"|"ammo"|"heavy"
            "pill_state": "none",       # "none"|"buff"|"debuff"
            "rank_bonus_pct": 29.7,      # Military Rank bonus % langsung (0-37.5), user cukup ingat angkanya
            "battle_bonus_pct": 29.7,   # Total Battle Bonus % (1 angka, simpel)
            "is_revolt": False,         # True jika revolt/liberation (cap 115%)
        }

    Returns: dict dengan Damage Contribution + Resource Cost + flags.
    """

    # ══════════════════════════════════════════════════════════
    # DAMAGE PATH (F015 §5)
    # ══════════════════════════════════════════════════════════

    # Step 1: Precision Gate — Miss check (F015 v1.3.0 VERIFIED)
    # Miss takes priority over Crit
    is_miss = random.random() > stats["precision_prob"]

    # Step 2: Critical Check (hanya jika tidak miss)
    is_crit = False
    if not is_miss:
        is_crit = random.random() <= stats["crit_chance_prob"]

    # Step 3: Personal Attack (F006 pipeline)
    # Attack × Ammo × Pill × Rank
    ammo_mult = AMMO_MULTIPLIERS.get(battle_config.get("ammo_tier", "ammo"), 1.20)
    pill_mult = PILL_MULTIPLIERS.get(battle_config.get("pill_state", "none"), 1.00)

    rank_bonus_pct = battle_config.get("rank_bonus_pct", 0) / 100.0
    rank_mult = 1 + rank_bonus_pct

    personal_attack = stats["attack"] * ammo_mult * pill_mult * rank_mult

    # Step 4: Battle Bonus (F007 — additive internal, lalu multiplicative)
    # User input 1 angka total, simulator handle cap
    bb_pct = battle_config.get("battle_bonus_pct", 0) / 100.0  # konversi ke desimal
    bb_cap = BATTLE_BONUS_CAP_REVOLT if battle_config.get("is_revolt") else BATTLE_BONUS_CAP_NORMAL
    bb_pct = min(bb_pct, bb_cap)
    battle_bonus_mult = 1 + bb_pct

    # Step 5: Final Damage per Hit
    final_damage = personal_attack * battle_bonus_mult

    # Step 6: Apply Miss/Crit modifiers (F015, F014 evidence #6)
    if is_miss:
        # Miss: 50% damage, no crit
        final_damage *= MISS_DAMAGE_MULTIPLIER
    elif is_crit:
        # Crit: × (1 + crit_dmg_mult)
        # crit_dmg_mult sudah dalam format 1.0 = 100% bonus
        # Jadi crit hit = damage × (1 + 1.0) = 2× untuk crit_dmg 100%
        final_damage *= (1 + stats["crit_dmg_mult"])

    damage_contribution = round(final_damage)

    # ══════════════════════════════════════════════════════════
    # RESOURCE COST PATH (F015 §6)
    # ══════════════════════════════════════════════════════════

    # Base Health Cost (F010) = 10
    base_hp_cost = BASE_HEALTH_COST

    # Step 1: Dodge Check (F009)
    is_dodged = random.random() <= stats["dodge_eff"]

    if is_dodged:
        # Dodge berhasil: Health Cost = 0
        # Durability: hanya weapon -1%, lainnya 0 (F011 §5.2)
        final_hp_cost = 0
        durability_loss = {"weapon": -1}
    else:
        # Step 2: Armor Effectiveness (F008)
        final_hp_cost = base_hp_cost * (1 - stats["armor_eff"])
        # Durability: semua 6 slot -1% (F011 §5.1)
        durability_loss = {slot: -1 for slot in EQUIPMENT_SLOTS}

    final_hp_cost = round(final_hp_cost, 2)

    # ══════════════════════════════════════════════════════════
    # LOOT PATH (F014 — paralel, independen)
    # ══════════════════════════════════════════════════════════

    loot_pct = stats["loot_chance_pct"]  # 5-25
    case_chance_per_hit = loot_pct / 100.0              # e.g., 0.25 = 25%
    elite_case_chance_per_hit = case_chance_per_hit * LOOT_ELITE_CASE_RATIO  # 0.0025 = 0.25%

    # ══════════════════════════════════════════════════════════
    # RESULT
    # ══════════════════════════════════════════════════════════

    return {
        "damage_contribution": damage_contribution,
        "health_cost": final_hp_cost,
        "durability_loss": durability_loss,
        "is_miss": is_miss,
        "is_crit": is_crit,
        "is_dodged": is_dodged,
        "case_chance": case_chance_per_hit,
        "elite_case_chance": elite_case_chance_per_hit,
        # Breakdown untuk display
        "_breakdown": {
            "personal_attack": round(personal_attack, 2),
            "battle_bonus_mult": round(battle_bonus_mult, 4),
            "ammo_mult": ammo_mult,
            "pill_mult": pill_mult,
            "rank_mult": rank_mult,
            "base_damage": round(personal_attack * battle_bonus_mult, 2),
            "crit_multiplier": round(1 + stats["crit_dmg_mult"], 4) if is_crit else 1.0,
            "miss_multiplier": MISS_DAMAGE_MULTIPLIER if is_miss else 1.0,
        }
    }
