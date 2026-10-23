# services/economy/constants.py — konstanta data item/grade/mapping

from __future__ import annotations

ITEM_LABELS: dict[str, str] = {
    "iron":             "Iron",
    "grain":            "Grain",
    "wood":             "Wood",
    "oil":              "Oil",
    "limestone":        "Limestone",
    "lead":             "Lead",
    "mysterious_plant": "Mysterious Plant",
    "fish":             "Fish",
    "livestock":        "Livestock",
    "scraps":           "Scraps",
    "steel":            "Steel",
    "bread":            "Bread",
    "paper":            "Paper",
    "concrete":         "Concrete",
    "petroleum":        "Petroleum",
    "pill":             "Pill",
    "cooked_fish":      "Cooked Fish",
    "steak":            "Steak",
    "ammo":             "Ammo",
    "light_ammo":       "Light Ammo",
    "heavy_ammo":       "Heavy Ammo",
    "case1":            "Case 1",
    "case2":            "Case 2",
    "wooden_case":      "Wooden Case",
}

ITEM_SHORT: dict[str, str] = {
    "Iron":             "Iron",
    "Grain":            "Grain",
    "Wood":             "Wood",
    "Oil":              "Oil",
    "Limestone":        "Limestone",
    "Lead":             "Lead",
    "Mysterious Plant": "Myst.Plant",
    "Fish":             "Fish",
    "Livestock":        "Livestock",
    "Scraps":           "Scraps",
    "Steel":            "Steel",
    "Bread":            "Bread",
    "Paper":            "Paper",
    "Concrete":         "Concrete",
    "Petroleum":        "Petroleum",
    "Pill":             "Pill",
    "Cooked Fish":      "CookedFish",
    "Steak":            "Steak",
    "Ammo":             "Ammo",
    "Light Ammo":       "LightAmmo",
    "Heavy Ammo":       "HeavyAmmo",
    "Case 1":           "Case1",
    "Case 2":           "Case2",
    "Wooden Case":      "WoodCase",
}

EQUIPMENT_GRADES: dict[str, dict] = {
    "Common":    {"craft_scraps": 6,    "craft_steel": 1,  "dismantle_scraps": 6},
    "Uncommon":  {"craft_scraps": 18,   "craft_steel": 2,  "dismantle_scraps": 18},
    "Rare":      {"craft_scraps": 54,   "craft_steel": 4,  "dismantle_scraps": 54},
    "Epic":      {"craft_scraps": 162,  "craft_steel": 8,  "dismantle_scraps": 162},
    "Legendary": {"craft_scraps": 486,  "craft_steel": 16, "dismantle_scraps": 486},
    "Mythic":    {"craft_scraps": 1458, "craft_steel": 32, "dismantle_scraps": 1458},
}

API_KEY_TO_ITEM_ID: dict[str, str] = {
    "iron": "iron", "grain": "grain", "wood": "wood", "oil": "oil",
    "limestone": "limestone", "lead": "lead", "coca": "mysterious_plant",
    "fish": "fish", "livestock": "livestock", "scraps": "scraps",
    "steel": "steel", "bread": "bread", "paper": "paper",
    "concrete": "concrete", "petroleum": "petroleum", "cocain": "pill",
    "cookedFish": "cooked_fish", "steak": "steak", "ammo": "ammo",
    "lightAmmo": "light_ammo", "heavyAmmo": "heavy_ammo",
    "case1": "case1", "case2": "case2", "woodenCase": "wooden_case",
}

ITEM_ID_TO_API_KEY: dict[str, str] = {v: k for k, v in API_KEY_TO_ITEM_ID.items()}

AMMO_OR_CONSTRUCTION_IDS = {
    "limestone", "iron", "concrete", "steel", "wood",
    "paper", "lead", "light_ammo", "ammo", "heavy_ammo",
    "petroleum", "oil",
}

FOOD_OR_BUFF_IDS = {"grain", "livestock", "fish", "mysterious_plant"}

ITEM_LABEL_TO_CODE: dict[str, str] = {
    v: k for k, v in {
        "iron": "Iron", "grain": "Grain", "wood": "Wood", "oil": "Oil",
        "limestone": "Limestone", "lead": "Lead", "coca": "Mysterious Plant",
        "fish": "Fish", "livestock": "Livestock", "scraps": "Scraps",
        "steel": "Steel", "bread": "Bread", "paper": "Paper",
        "concrete": "Concrete", "petroleum": "Petroleum", "cocain": "Pill",
        "cookedFish": "Cooked Fish", "steak": "Steak", "ammo": "Ammo",
        "lightAmmo": "Light Ammo", "heavyAmmo": "Heavy Ammo",
        "case1": "Case 1", "case2": "Case 2", "woodenCase": "Wooden Case",
    }.items()
}

# Emoji per item, dipakai embed Discord (spy/economy/alert).
# Dipindah dari cogs/spy/constants.py + cogs/economy/base.py (session 29 Sep).
ITEM_EMOJI: dict[str, str] = {
    "Iron": "⚙️", "Grain": "🌾", "Wood": "🪵", "Oil": "🛢️",
    "Limestone": "🪨", "Lead": "🪨", "Mysterious Plant": "🌿",
    "Fish": "🐟", "Livestock": "🐄", "Scraps": "🔩",
    "Steel": "🔧", "Bread": "🍞", "Paper": " 📄", "Concrete": "🧱",
    "Petroleum": "⛽", "Pill": "💊", "Cooked Fish": "🍣",
    "Steak": "🥩", "Ammo": "🟡", "Light Ammo": "🔴", "Heavy Ammo": "🔵",
    "Case 1": "📦", "Case 2": "📦", "Wooden Case": "🎁",
}

# --- production chain ---

ITEM_NOT_PRODUCIBLE: set[str] = {"Scraps", "Case 1", "Case 2", "Wooden Case"}

PRODUCTION_CHAIN: dict[str, dict] = {
    "Iron":             {"pp": 1,   "input": None},
    "Grain":            {"pp": 1,   "input": None},
    "Wood":             {"pp": 1,   "input": None},
    "Petroleum":        {"pp": 1,   "input": None},
    "Limestone":        {"pp": 1,   "input": None},
    "Lead":             {"pp": 1,   "input": None},
    "Mysterious Plant": {"pp": 1,   "input": None},
    "Fish":             {"pp": 40,  "input": None},
    "Livestock":        {"pp": 20,  "input": None},
    "Oil":              {"pp": 1,   "input": ("Petroleum",         1)},
    "Steel":            {"pp": 10,  "input": ("Iron",             10)},
    "Concrete":         {"pp": 10,  "input": ("Limestone",        10)},
    "Paper":            {"pp": 1,   "input": ("Wood",              1)},
    "Light Ammo":       {"pp": 1,   "input": ("Lead",              1)},
    "Ammo":             {"pp": 4,   "input": ("Lead",              4)},
    "Heavy Ammo":       {"pp": 16,  "input": ("Lead",             16)},
    "Bread":            {"pp": 10,  "input": ("Grain",            10)},
    "Steak":            {"pp": 20,  "input": ("Livestock",         1)},
    "Cooked Fish":      {"pp": 40,  "input": ("Fish",              1)},
    "Pill":             {"pp": 200, "input": ("Mysterious Plant", 200)},
}

# --- fairprice thresholds ---

CONFIDENCE_GATE = 70.0
LIQ_DISPLAY_HIGH = 0.65
LIQ_DISPLAY_MED = 0.35
