# tests/test_inventory_engine.py — behavior test helper murni inventory_engine
"""Snapshot + negatif. Bukan differential ke git — ini test perilaku,
biar tahan lama walau main berubah. Konservasi byte sudah divalidasi terpisah.
"""
from __future__ import annotations

from services.spy import inventory_engine as ie


# --- konstanta ---

def test_scrap_map_snapshot():
    assert dict(ie._SCRAP_MAP) == {
        2: ["common"],
        6: ["uncommon", "common"],
        18: ["rare", "uncommon"],
        54: ["epic", "rare"],
        162: ["legendary", "epic"],
        486: ["mythic", "legendary"],
        1458: ["mythic"],
    }


def test_suffix_rarity_snapshot():
    assert ie._SUFFIX_RARITY == {
        "1": "common", "2": "uncommon", "3": "rare",
        "4": "epic", "5": "legendary", "6": "mythic",
    }


# --- _slot_from_code ---

def test_slot_from_code_keywords():
    assert ie._slot_from_code("rifle3") == "weapon"
    assert ie._slot_from_code("helmet") == "helmet"
    assert ie._slot_from_code("xxx") == "unknown"


# --- _rarity_from_code ---

def test_rarity_from_code_paths():
    assert ie._rarity_from_code("sniper") == "epic"           # weapon map
    assert ie._rarity_from_code("a3") == "rare"               # suffix digit
    assert ie._rarity_from_code("unknown", "EPIC") == "epic"  # raw fallback
    assert ie._rarity_from_code("unknown", None) == "common"  # default


# --- _norm_skills ---

def test_norm_skills():
    assert ie._norm_skills(None) == {}
    assert ie._norm_skills({"a": 1, "b": "2"}) == {"a": "1", "b": "2"}


# --- _item_power ---

def test_item_power():
    assert ie._item_power({}) == 0
    assert ie._item_power({"a": "5", "b": "10"}) == 15
    assert ie._item_power({"a": "bad"}) == 0


# --- _make_item ---

def test_make_item_full():
    out = ie._make_item({"_id": "a", "code": "rifle3", "rarity": "RARE", "skills": {"atk": "10"}})
    assert out == {"_id": "a", "code": "rifle3", "rarity": "rare", "slot": "weapon", "skills": {"atk": "10"}}


def test_make_item_minimal():
    out = ie._make_item({"code": "knife"})
    assert out["_id"] is None
    assert out["code"] == "knife"


# --- _remove_item fallback bertingkat ---

def _mk(_id, code, rar, skills):
    return {"_id": _id, "code": code, "rarity": rar, "skills": skills}


def test_remove_item_id_match():
    inv = {"w": [_mk("x", "rifle", "rare", {"a": "1"}), _mk("y", "rifle", "rare", {"a": "2"})]}
    removed, how = ie._remove_item(inv, _mk("y", "rifle", "rare", {"a": "2"}))
    assert how == "id_match"
    assert removed["_id"] == "y"


def test_remove_item_fifo_fallback():
    inv = {"w": [_mk("x", "rifle", "rare", {"a": "1"})]}
    removed, how = ie._remove_item(inv, {"code": "rifle", "rarity": "epic", "skills": {"a": "2"}})
    assert how == "fifo"
    assert removed["_id"] == "x"


def test_remove_item_not_found():
    inv = {"w": []}
    removed, how = ie._remove_item(inv, {"code": "rifle", "rarity": "rare", "skills": {}})
    assert removed is None
    assert how == "not_found"


# --- _remove_worst_by_rarity ---

def test_remove_worst_by_rarity_picks_lowest_power():
    inv = {"w": [
        _mk("a", "x", "rare", {"p": "5"}),
        _mk("b", "x", "rare", {"p": "1"}),
        _mk("c", "x", "epic", {"p": "9"}),
    ]}
    out = ie._remove_worst_by_rarity(inv, "rare")
    assert out["_id"] == "b"  # power terendah


def test_remove_worst_by_rarity_empty():
    assert ie._remove_worst_by_rarity({"w": []}, "rare") is None


# --- NEGATIF: helper harus murni (tidak akses self / I/O) ---

def test_helpers_have_no_self_access():
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(ie.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            raise AssertionError(f"self.* ditemukan di {ie.__file__}:{node.lineno}")


def test_helpers_no_io_imports():
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(ie.__file__).read_text())
    banned = {"market", "discord", "psycopg2", "requests", "aiohttp"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned, f"I/O import: {a.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, f"I/O import: {node.module}"
