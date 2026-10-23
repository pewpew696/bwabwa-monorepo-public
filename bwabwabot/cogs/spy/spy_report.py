"""
spy_report.py
Generator gambar "spy report" untuk bot Discord xspy (WarEra).
"""

import os

from PIL import Image, ImageDraw, ImageFont

from .avatar_processing import paste_avatar

# =========================
# FILE
# =========================
# __file__-relative: cogs/spy/spy_report.py -> naik 3 level ke root repo,
# lalu masuk assets/spy_assets/. Gak bergantung dari mana bot dijalankan
# (CWD), beda dari versi beta yang pakai path relatif ke CWD.
_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "spy_assets",
)
TEMPLATE = os.path.join(_ASSETS_DIR, "spy_report.png")
FONT = os.path.join(_ASSETS_DIR, "SpecialElite-Regular.ttf")

# =========================
# FONT SIZE
# =========================
FONT_MAIN = 30
FONT_SKILL_LVL = 24
FONT_TBS = 28
FONT_DAMAGE = 70

COLOR_BLACK = "black"
COLOR_RED = (180, 0, 0)
COLOR_GREEN = (0, 130, 0)

# =========================
# KOORDINAT - PROFILE
# =========================
USN = (357, 116)
LEVEL = (368, 145)
LOCATION = (402, 170)
MU = (345, 198)

MIL_RANK = (811, 116)
LAST_SEEN = (778, 145)
BUILD = (728, 170)
STATUS = (790, 194)
BUFF_DEBUFF = (738, 220)

# =========================
# KOORDINAT - BASE STATS
# =========================
SKILL_LVL_X = 290
SKILL_STAT_X = 368

BASE_STAT_Y = {
    "attack": 330,
    "precision": 357,
    "crit_chance": 385,
    "crit_damage": 413,
    "armor": 439,
    "dodge": 464,
    "hp": 491,
    "hunger": 515,
    "loot": 542,
    "company": 566,
    "energy": 593,
    "production": 619,
    "management": 644,
    "entrepreneurship": 672,  # baris paling bawah di template, di bawah Management.
                              # Kalau posisinya masih kepotong/kurang pas pas dites,
                              # tinggal geser angka ini naik-turun beberapa pixel.
}

# =========================
# KOORDINAT - TOTAL BATTLE STATS
# =========================
TBS_VALUE_X = 716

TBS_Y = {
    "attack": 308,
    "precision": 340,
    "crit_chance": 370,
    "crit_damage": 399,
    "armor": 429,
    "dodge": 462,
}

# =========================
# KOORDINAT - DAMAGE LOG
# =========================
WEEKLY_DMG = (562, 620)
TOTAL_DMG = (902, 620)


def generate_spy_report(data: dict, avatar_path: str | None, output_path: str = "preview.png") -> str:
    """
    Bikin gambar spy report dari data player asli.

    Struktur `data` yang diharapkan:
    {
        "usn": "MashaAndTheRawr",
        "level": "47",
        "location": "LaosNihBos",
        "mu": "GasakMase",
        "mil_rank": "23.25%",
        "last_seen": "Online",
        "build": "WAR",
        "status": "ACTIVE",              # atau "INACTIVE", dll
        "buff_debuff": "✅ Clean",        # atau "💊 Active ...", "🤢 Debuff active ..."
        "base_stats": {                  # key harus cocok BASE_STAT_Y
            "attack": ("6", "250"),
            "precision": ("4", "70"),
            "crit_chance": ("5", "35%"),
            "crit_damage": ("4", "150%"),
            "armor": ("3", "18"),
            "dodge": ("3", "12"),
            "hp": ("3", "130"),
            "hunger": ("3", "130"),
            "loot": ("3", "11%"),
            "company": ("3", "+25%"),
            "energy": ("2", "120"),
            "production": ("4", "+20%"),
            "management": ("1", "+5%"),
            "entrepreneurship": ("3", "45%"),
        },
        "tbs": {                         # key harus cocok TBS_Y
            "attack": "470",
            "precision": "82",
            "crit_chance": "41%",
            "crit_damage": "195%",
            "armor": "22%",
            "dodge": "15%",
        },
        "weekly_dmg": "2.84M",
        "total_dmg": "41.72M",
    }

    avatar_path: path ke file gambar avatar player (hasil download dari WarEra),
                 atau None kalau download avatar gagal — report tetap dibuat,
                 kotak avatar dibiarkan kosong.
    output_path: path file hasil akhir (dikembalikan sebagai return value,
                 tinggal dipakai bot buat discord.File(output_path)).
    """
    font_main = ImageFont.truetype(FONT, FONT_MAIN)
    font_skill_lvl = ImageFont.truetype(FONT, FONT_SKILL_LVL)
    font_tbs = ImageFont.truetype(FONT, FONT_TBS)
    font_damage = ImageFont.truetype(FONT, FONT_DAMAGE)

    # 1. load template
    img = Image.open(TEMPLATE).convert("RGBA")

    # 2. tempel avatar dulu, sebelum teks (avatar None -> paste_avatar skip,
    #    template dipakai apa adanya)
    avatar = Image.open(avatar_path) if avatar_path else None
    img = paste_avatar(img, avatar)

    # 3. baru gambar teks di atasnya
    draw = ImageDraw.Draw(img)

    # --- profile ---
    draw.text(USN, data["usn"], font=font_main, fill=COLOR_BLACK)
    draw.text(LEVEL, str(data["level"]), font=font_main, fill=COLOR_BLACK)
    draw.text(LOCATION, data["location"], font=font_main, fill=COLOR_BLACK)
    draw.text(MU, data["mu"], font=font_main, fill=COLOR_BLACK)

    draw.text(MIL_RANK, data["mil_rank"], font=font_main, fill=COLOR_BLACK)
    draw.text(LAST_SEEN, data["last_seen"], font=font_main, fill=COLOR_BLACK)
    draw.text(BUILD, data["build"], font=font_main, fill=COLOR_BLACK)

    status_color = COLOR_GREEN if data["status"].upper() == "ACTIVE" else COLOR_RED
    draw.text(STATUS, data["status"], font=font_main, fill=status_color)
    draw.text(BUFF_DEBUFF, data["buff_debuff"], font=font_main, fill=COLOR_BLACK)

    # --- base stats ---
    for key, y in BASE_STAT_Y.items():
        lvl, val = data["base_stats"][key]
        draw.text((SKILL_LVL_X, y), str(lvl), font=font_skill_lvl, fill=COLOR_BLACK)
        draw.text((SKILL_STAT_X, y), str(val), font=font_skill_lvl, fill=COLOR_BLACK)

    # --- total battle stats ---
    for key, y in TBS_Y.items():
        draw.text((TBS_VALUE_X, y), str(data["tbs"][key]), font=font_tbs, fill=COLOR_BLACK)

    # --- damage log ---
    draw.text(WEEKLY_DMG, data["weekly_dmg"], font=font_damage, fill=COLOR_RED)
    draw.text(TOTAL_DMG, data["total_dmg"], font=font_damage, fill=COLOR_RED)

    # 4. save
    img.convert("RGB").save(output_path)
    return output_path


if __name__ == "__main__":
    # contoh pemakaian standalone (dummy data, buat testing lokal)
    dummy_data = {
        "usn": "MashaAndTheRawr",
        "level": "47",
        "location": "LaosNihBos",
        "mu": "GasakMase",
        "mil_rank": "23.25%",
        "last_seen": "Online",
        "build": "WAR",
        "status": "ACTIVE",
        "buff_debuff": "✅ Clean",
        "base_stats": {
            "attack": ("6", "250"),
            "precision": ("4", "70"),
            "crit_chance": ("5", "35%"),
            "crit_damage": ("4", "150%"),
            "armor": ("3", "18"),
            "dodge": ("3", "12"),
            "hp": ("3", "130"),
            "hunger": ("3", "130"),
            "loot": ("3", "11%"),
            "company": ("3", "+25%"),
            "energy": ("2", "120"),
            "production": ("4", "+20%"),
            "management": ("1", "+5%"),
            "entrepreneurship": ("3", "45%"),
        },
        "tbs": {
            "attack": "470",
            "precision": "82",
            "crit_chance": "41%",
            "crit_damage": "195%",
            "armor": "22%",
            "dodge": "15%",
        },
        "weekly_dmg": "2.84M",
        "total_dmg": "41.72M",
    }

    out = generate_spy_report(dummy_data, "avatar_warera.png", "preview.png")
    print("Selesai! File tersimpan:", out)
