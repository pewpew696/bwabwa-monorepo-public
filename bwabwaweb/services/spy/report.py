# services/spy/report.py — fungsi murni bangun report data player

from __future__ import annotations

from services.spy.utils import (
    classify_build,
    effective,
    fmt_k,
    last_seen,
    pill_status,
)


# --- report data ---

def build_report_data(data: dict, mu_name: str, country_name: str) -> dict:
    """Bangun dict report player dari data user lite."""
    leveling = data.get("leveling", {})
    skills = data.get("skills", {})
    spent = int(leveling.get("spentSkillPoints") or 0)

    attack_obj = skills.get("attack", {})
    crit_c_obj = skills.get("criticalChance", {})
    crit_d_obj = skills.get("criticalDamages", {})
    armor_obj = skills.get("armor", {})
    dodge_obj = skills.get("dodge", {})
    prec_obj = skills.get("precision", {})
    health_obj = skills.get("health", {})
    hunger_obj = skills.get("hunger", {})

    rankings = data.get("rankings", {})
    dmg_weekly = float((rankings.get("weeklyUserDamages") or {}).get("value") or 0)
    dmg_total = float((rankings.get("userDamages") or {}).get("value") or 0)

    def lv(obj: dict) -> str:
        return str(int(obj.get("level") or 0))

    return {
        "usn": data.get("username", "?"),
        "level": str(leveling.get("level", "?")),
        "location": country_name,
        "mu": mu_name,
        "mil_rank": f"{float(attack_obj.get('militaryRankPercent') or 0):.2f}%",
        "last_seen": last_seen(data.get("dates", {})),
        "build": classify_build(skills, spent),
        "status": "ACTIVE" if data.get("isActive") else "INACTIVE",
        "buff_debuff": pill_status(data),

        "base_stats": {
            "attack": (lv(attack_obj), f"{float(attack_obj.get('value') or 0):.0f}"),
            "precision": (lv(prec_obj), f"{float(prec_obj.get('value') or 0):.0f}"),
            "crit_chance": (lv(crit_c_obj), f"{float(crit_c_obj.get('value') or 0):.0f}%"),
            "crit_damage": (lv(crit_d_obj), f"{float(crit_d_obj.get('value') or 0):.0f}%"),
            "armor": (lv(armor_obj), f"{float(armor_obj.get('equipment') or 0):.0f}"),
            "dodge": (lv(dodge_obj), f"{float(dodge_obj.get('equipment') or 0):.0f}"),
            "hp": (lv(health_obj), f"{float(health_obj.get('value') or 0):.0f}"),
            "hunger": (lv(hunger_obj), f"{float(hunger_obj.get('value') or 0):.0f}"),
            "loot": (lv(skills.get("lootChance", {})), f"{float(skills.get('lootChance', {}).get('value') or 0):.0f}%"),
            "company": (lv(skills.get("companies", {})), f"{float(skills.get('companies', {}).get('value') or 0):.0f}"),
            "energy": (lv(skills.get("energy", {})), f"{float(skills.get('energy', {}).get('value') or 0):.0f}"),
            "production": (lv(skills.get("production", {})), f"{float(skills.get('production', {}).get('value') or 0):.0f}"),
            "management": (lv(skills.get("management", {})), f"{float(skills.get('management', {}).get('value') or 0):.0f}"),
            "entrepreneurship": (lv(skills.get("entrepreneurship", {})), f"{float(skills.get('entrepreneurship', {}).get('value') or 0):.0f}"),
        },

        "tbs": {
            "attack": f"{float(attack_obj.get('total') or 0):.0f}",
            "precision": f"{min(float(prec_obj.get('total') or 0), 100):.0f}",
            "crit_chance": f"{float(crit_c_obj.get('total') or 0):.0f}%",
            "crit_damage": f"{float(crit_d_obj.get('total') or 0):.0f}%",
            "armor": f"{effective(armor_obj):.0f}%",
            "dodge": f"{effective(dodge_obj):.0f}%",
        },

        "weekly_dmg": fmt_k(dmg_weekly),
        "total_dmg": fmt_k(dmg_total),
    }
