"""
services/spy/utils.py — fungsi murni (formatting, klasifikasi, parsing tanggal)
yang dipakai SpyCog. Tidak ada yang menyentuh network/Discord/Supabase di
sini, jadi gampang di-unit-test terpisah kalau diperlukan nanti.
"""

from __future__ import annotations

from datetime import datetime, timezone


from services.spy.constants import ECO_SKILLS, RARITY_LABELS, RARITY_STAT_RANGES

# fmt_k canonical di core/formatters.py (session 29 Sep). Re-export.
from core.formatters import fmt_compact as fmt_k  # noqa: F401
def get_stat(skill: dict, field: str = "total") -> float:
    return float(skill.get(field) or 0)


def effective(skill: dict) -> float:
    v = skill.get("totalAfterSoftCap")
    if v is not None:
        return float(v)
    return float(skill.get("total") or 0)


def rarity_from_code(code: str | None) -> str:
    """Ekstrak label rarity dari suffix angka pada `code` item equipment
    (mis. 'chest4' -> '🟣 Ungu'). Balikin '❓' kalau code kosong/gak dikenali
    (contoh: weapon kadang code-nya tanpa suffix angka, mis. 'knife').
    STATUS: baru 3 data point terverifikasi, dipakai sebagai cross-check
    sekunder — bukan basis utama classifier (lihat classify_stat_range)."""
    if not code:
        return "❓"
    import re
    m = re.search(r"(\d+)$", code)
    if not m:
        return "❓"
    tier = int(m.group(1))
    return RARITY_LABELS.get(tier, f"❓ (tier {tier})")


def classify_stat_range(category: str, value: float) -> str:
    """Cocokkan nilai stat mentah (bonus gear, bukan total) ke tier rarity
    pakai RARITY_STAT_RANGES. Ini basis utama classifier rarity di bot,
    karena tabelnya udah diverifikasi user dan gap antar tier itu memang
    by-design dari game (bukan celah karena kurang data)."""
    ranges = RARITY_STAT_RANGES.get(category)
    if not ranges or value <= 0:
        return "❓"
    for label, lo, hi in ranges:
        if lo <= value <= hi:
            return label
    if value < ranges[0][1]:
        return f"❓ (below {ranges[0][1]})"
    if value > ranges[-1][2]:
        return f"❓ (above {ranges[-1][2]})"
    return "❓ (unexpected gap)"


def skill_cost(level: int) -> int:
    return level * (level + 1) // 2


def classify_build(skills: dict, spent: int) -> str:
    eco_pts = sum(
        skill_cost(int(skills.get(s, {}).get("level", 0) or 0))
        for s in ECO_SKILLS
    )
    war_pts = sum(
        skill_cost(int(skills.get(s, {}).get("level", 0) or 0))
        for s in skills
        if s not in ECO_SKILLS
    )
    allocated = eco_pts + war_pts
    if allocated == 0:
        return "⚖️ Hybrid"
    eco_pct = eco_pts / allocated * 100
    war_pct = war_pts / allocated * 100
    if eco_pct >= 60:
        return "💰 Eco"
    if war_pct >= 60:
        return "⚔️ War"
    return "⚖️ Hybrid"


def last_seen(dates: dict) -> str:
    last = dates.get("lastConnectionAt")
    if not last:
        return "—"
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        minutes = int(diff.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return "—"


def ago(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        minutes = int(diff.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h{mins:02d}m ago"
    except Exception:
        return "?"


def pill_status(data: dict) -> str:
    buffs = data.get("buffs") or {}
    buff_codes = buffs.get("buffCodes") or []
    buff_end = buffs.get("buffEndAt")
    debuff_end = buffs.get("debuffEndAt")
    attack = data.get("skills", {}).get("attack", {})
    debuffs_pct = float(attack.get("debuffsPercent") or 0)
    buffs_pct = float(attack.get("buffsPercent") or 0)

    # Buff countdown
    if buff_codes and buff_end:
        try:
            end_dt = datetime.fromisoformat(buff_end.replace("Z", "+00:00"))
            remaining = (end_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                return f"💊 Active — {h}h {m:02d}m left (+{buffs_pct:.0f}% ATT)"
        except Exception:
            pass
        return f"💊 Active (+{buffs_pct:.0f}% ATT)"

    # Debuff countdown
    if debuff_end and debuffs_pct > 0:
        try:
            end_dt = datetime.fromisoformat(debuff_end.replace("Z", "+00:00"))
            remaining = (end_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                return f"🤢 Debuff — {h}h {m:02d}m left (-{debuffs_pct:.0f}%)"
        except Exception:
            pass
        return f"🤢 Debuff active (-{debuffs_pct:.0f}%)"

    if debuffs_pct > 0:
        return f"🤢 Debuff active (-{debuffs_pct:.0f}%)"

    return "✅ Clean"


def tx_money_delta(tx: dict, user_id: str) -> float:
    money = float(tx.get("money") or 0)
    if money == 0:
        return 0.0
    buyer = tx.get("buyerId")
    seller = tx.get("sellerId")
    if buyer == user_id:
        return money
    if seller == user_id:
        return -money
    return 0.0

def not_found_msg(kind: str, nama: str, suggestions: list[str], *, md: bool = False) -> str:
    """Pesan 'gak ketemu persis' + opsi yang ada. md=True buat Discord (backtick)."""
    q = f"`{nama}`" if md else f"'{nama}'"
    msg = f"{kind} {q} not found."
    if suggestions:
        opts = ", ".join(f"`{s}`" if md else s for s in suggestions)
        msg += f" No exact match — closest results: {opts}"
    return msg
