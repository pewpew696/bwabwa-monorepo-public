# services/spy/constants.py — konstanta murni SpyCog (diekstrak 28 Sep 2026)
# Diekstrak dari cogs/spy/constants.py (zero logic change).
# Isi + type annotation sama persis; hanya lokasi yang pindah.

from __future__ import annotations


# ECO skills
ECO_SKILLS = {"production", "entrepreneurship", "energy", "companies", "management"}


# Mapping tier rarity (angka suffix di `code` item, mis. "chest4" -> Purple).
# STATUS: berdasarkan pola empiris terbatas (chest1=White armor4, pants3=Blue
# armor14, chest4=Purple armor29) — cross-check dengan Equipment_Rarity_Stat_Ranges.md.
# Kalau ternyata ada slot yang numbering-nya beda urutan, revisi dict ini.
RARITY_LABELS: dict[int, str] = {
    1: "⚪ White",
    2: "🟢 Green",
    3: "🔵 Blue",
    4: "🟣 Purple",
    5: "🟠 Orange",
    6: "🔴 Red",
}


# Range stat mentah (nilai bonus gear per-item, BUKAN total setelah base stat)
# per tier rarity. Sumber: riset user (Equipment_Rarity_Stat_Ranges.md), dengan
# 2 koreksi yang sudah dikonfirmasi empiris oleh user:
#   - Weapon ATK White max 40 (bukan 40 lama / gap ke Green di 41-49)
#   - Weapon ATK Green min 50 (bukan 51)
#   - Weapon ATK Red max 300 (dikonfirmasi = cap resmi gabungan, bukan 200)
# Gap antar tier di sini SENGAJA (ditetapkan game, dikonfirmasi user) — kalau
# ada value yang jatuh di gap, itu tanda ada yang salah baca, bukan rarity baru.
# CATATAN: Weapon ATK/Crit belum dipisah per tipe senjata (Knife/Gun/Rifle/
# Sniper/Tank/Jet) — kemungkinan tiap tipe punya range sendiri, jadi klasifikasi
# weapon di bawah ini masih indikatif, prioritaskan armor/dodge/precision/critdmg.
RARITY_STAT_RANGES: dict[str, list[tuple[str, float, float]]] = {
    "weapon_atk": [
        ("⚪ White", 21, 40),
        ("🟢 Green", 50, 60),
        ("🔵 Blue", 71, 90),
        ("🟣 Purple", 101, 130),
        ("🟠 Orange", 141, 170),
        ("🔴 Red", 221, 300),
    ],
    "weapon_crit_chance": [
        ("⚪ White", 1, 5),
        ("🟢 Green", 6, 10),
        ("🔵 Blue", 11, 15),
        ("🟣 Purple", 16, 20),
        ("🟠 Orange", 26, 35),
        ("🔴 Red", 41, 50),
    ],
    "helmet_crit_dmg": [
        ("⚪ White", 1, 15),
        ("🟢 Green", 16, 30),
        ("🔵 Blue", 31, 50),
        ("🟣 Purple", 71, 90),
        ("🟠 Orange", 91, 110),
        ("🔴 Red", 121, 150),
    ],
    "armor": [  # Chest & Pants, per slot
        ("⚪ White", 1, 5),
        ("🟢 Green", 6, 10),
        ("🔵 Blue", 11, 15),
        ("🟣 Purple", 21, 30),
        ("🟠 Orange", 36, 50),
        ("🔴 Red", 56, 70),
    ],
    "dodge": [  # Boots
        ("⚪ White", 1, 5),
        ("🟢 Green", 6, 10),
        ("🔵 Blue", 11, 15),
        ("🟣 Purple", 21, 25),
        ("🟠 Orange", 26, 40),
        ("🔴 Red", 51, 60),
    ],
    "precision": [  # Gloves
        ("⚪ White", 1, 5),
        ("🟢 Green", 6, 10),
        ("🔵 Blue", 11, 15),
        ("🟣 Purple", 21, 25),
        ("🟠 Orange", 31, 40),
        ("🔴 Red", 51, 60),
    ],
}

