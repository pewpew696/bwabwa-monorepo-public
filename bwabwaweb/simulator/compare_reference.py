"""
Pembanding engine vs dua sampel screenshot WarEra Intel. Dijalankan manual:
    PYTHONPATH=. python -m simulator.compare_reference

ASUMSI (tidak terlihat di screenshot, diisi best-effort):
  - char_level 50 (tidak dipakai calculate_base_stats)
  - rank_bonus_pct 20.75 ("3-star Captain" di constants.py), battle_bonus_pct 60,
    pill buff, ammo light, is_revolt False
  - hits_per_day = angka ammo di screenshot (241 / 207), 1 ammo per hit
  - mapping ikon skill dan rarity gear per slot: best-effort dari tampilan; rarity build_2
    diduga keliru (biaya wear meleset sekitar -38%)
  - harga: Scraps, Steel, Light Ammo, Steak, Iron dari user; harga case memakai bawaan constants
  - "net" dan "gold_per_k" di screenshot adalah biaya bersih (positif = rugi), dibalik jadi laba
  - Revisi 2026-10-08 (Fase 1): scrap_income & battle loot SUDAH dimodelkan engine
    (F017/F018, probe Warera Build Tool). Screenshot Intel lama diduga pre-nerf
    buat battle loot (k ~0.171/K vs probe 0.054/K) — selisih loot vs screenshot
    belum tentu bug engine, flag buat owner.
"""

from simulator.engine import calculate_base_stats, calculate_daily_projection, quick_simulate

# Skill dari screenshot (2 baris: 5 icon + 4 icon): sword=attack, crosshair=precision,
# bullseye=crit_chance, target+arrow=crit_damage, shield=armor, running=dodge, heart=health,
# chest=loot_chance, fork=hunger
SKILLS_SAMPLE = {
    "attack": 6, "precision": 6, "crit_chance": 5, "crit_damage": 4, "armor": 3,
    "dodge": 4, "health": 4, "loot_chance": 3, "hunger": 2,
}

SAMPLES = {
    "build_1": {
        "label": "728.7K dmg, biaya bersih +69.96",
        "equipment": {
            "weapon": {"rarity": "Ungu", "stats": {"weapon_atk": 107, "weapon_crit_chance": 20}, "durability": 100},
            "helmet": {"rarity": "Ungu", "stats": {"helmet_crit_dmg": 76}, "durability": 100},
            "gloves": {"rarity": "Ungu", "stats": {"precision": 23}, "durability": 100},
            "chest": {"rarity": "Biru", "stats": {"armor": 15}, "durability": 100},
            "pants": {"rarity": "Ungu", "stats": {"armor": 29}, "durability": 100},
            "boots": {"rarity": "Ungu", "stats": {"dodge": 23}, "durability": 100},
        },
        "hits_per_day": 241,
        "reference": {
            "daily_damage": 728700, "net_cost": 69.96, "cost_per_k": 0.10,
            "gear_cost": 369.75, "consumables_cost": 124.27,
            "scrap_income": 90.42, "case_income": 94.86,
            "loot_income": 124.51, "company_income": 114.26,
        },
    },
    "build_2": {
        "label": "568.7K dmg, biaya bersih -6.56",
        "equipment": {
            "weapon": {"rarity": "Ungu", "stats": {"weapon_atk": 104, "weapon_crit_chance": 20}, "durability": 100},
            "helmet": {"rarity": "Biru", "stats": {"helmet_crit_dmg": 45}, "durability": 100},
            "gloves": {"rarity": "Ungu", "stats": {"precision": 22}, "durability": 100},
            "chest": {"rarity": "Ungu", "stats": {"armor": 24}, "durability": 100},
            "pants": {"rarity": "Biru", "stats": {"armor": 15}, "durability": 100},
            "boots": {"rarity": "Biru", "stats": {"dodge": 15}, "durability": 100},
        },
        "hits_per_day": 207,
        "reference": {
            "daily_damage": 568700, "net_cost": -6.56, "cost_per_k": -0.01,
            "gear_cost": 233.87, "consumables_cost": 117.37,
            "scrap_income": 65.09, "case_income": 81.28,
            "loot_income": 97.17, "company_income": 114.26,
        },
    },
}

BATTLE_CONFIG = {
    "ammo_tier": "light",          # user kasih harga Light Ammo, bukan Ammo/Heavy
    "pill_state": "buff",          # "+buff pill 60%" -> PILL_MULTIPLIERS["buff"]
    "rank_bonus_pct": 20.75,
    "battle_bonus_pct": 60,
    "is_revolt": False,
}

ECONOMY_CONFIG = {
    "food_type": "Steak",
    "market_prices": {
        "Scraps": 0.219, "Steel": 1.62, "Light Ammo": 0.166, "Steak": 3.68,
        "Iron": 0.08,  # harga asli dari user
    },
    "companies": [{"ae_level": 6, "production_target": "Iron"} for _ in range(6)],
}


def project(name):
    """Proyeksi harian engine untuk satu sampel."""
    sample = SAMPLES[name]
    stats = calculate_base_stats(SKILLS_SAMPLE, sample["equipment"], char_level=50)
    qs = quick_simulate(stats, BATTLE_CONFIG)
    return calculate_daily_projection(
        qs, stats, BATTLE_CONFIG, ECONOMY_CONFIG,
        hits_per_day=sample["hits_per_day"], equipment=sample["equipment"],
    )


def _print_row(label, eng, ref_v):
    delta = eng - ref_v
    pct = (delta / ref_v * 100) if ref_v else float("inf")
    print(f"{label:<22}{eng:>15.2f}{ref_v:>15.2f}{delta:>+14.2f} ({pct:+.0f}%)")


def main():
    for name, sample in SAMPLES.items():
        ref = sample["reference"]
        proj = project(name)
        print("=" * 70)
        print(f"{name} ({sample['label']})")
        print("=" * 70)
        print(f"{'metric':<22}{'engine.py':>15}{'WarEra Intel':>15}{'delta':>15}")
        _print_row("daily_damage", proj["daily_damage"], ref["daily_damage"])
        _print_row("daily_wear_cost", proj["daily_wear_cost"], ref["gear_cost"])
        _print_row("daily_ammo+food_cost", proj["daily_ammo_cost"] + proj["daily_food_cost"],
                   ref["consumables_cost"])
        # engine: case + elite case; Intel: case_income
        _print_row("daily_loot_income", proj["daily_loot_income"], ref["case_income"])
        _print_row("daily_company_income", proj["daily_company_income"], ref["company_income"])
        _print_row("daily_scrap_income", proj["daily_scrap_income"], ref["scrap_income"])
        _print_row("daily_battle_loot", proj["daily_battle_loot_income"], ref["loot_income"])
        _print_row("daily_net_profit", proj["daily_net_profit"], -ref["net_cost"])
        _print_row("gold_per_k", proj["gold_per_k"], -ref["cost_per_k"])
        print(f"{'daily_food_eaten':<22}{proj['daily_food_eaten']:>15.1f}  (selisih dari Intel disengaja, lihat DEBT.md)")
        print()


if __name__ == "__main__":
    main()
