"""simulator/cycle_cache.py — cache TTL untuk hasil fase buff (F016).

Niru pola web_api/access_monitor.py (threading.Lock + dict module-level +
cek freshness sebelum baca/tulis), supaya konsisten sama gaya kode yang
sudah ada di project ini.

Kenapa TTL pendek (15 menit), BUKAN ikut durasi session (30 hari):
hasil fase buff ngandung angka ekonomi (loot_income/ammo_cost/food_cost/
wear_cost) yang dihitung dari harga market saat itu (_price_cache, refresh
~15 menit — PRICE_REFRESH_MIN). Kalau cache-nya lebih awet dari itu, angka
ekonominya jadi basi walau skill+equipment-nya sama persis (keputusan user
2026-09-03).

1 slot per session (key = session_id + hash input fase buff) — regenerate
otomatis replace slot yang sama, bukan akumulasi banyak entry.
"""

import hashlib
import json
import threading
import time

CACHE_TTL_SECONDS = 15 * 60  # 15 menit, disamakan siklus refresh _price_cache

_cache: dict = {}   # key -> {"result": dict, "stored_at": float}
_lock = threading.Lock()


def _hash_buff_input(skills: dict, equipment: dict, battle_config: dict,
                      char_level: int, food_type: str) -> str:
    """Hash deterministik dari input yang menentukan hasil fase buff.
    Ganti gear fase debuff doang TIDAK mengubah hash ini -> cache tetap valid."""
    payload = {
        "skills": skills,
        "equipment": equipment,
        "battle_config": battle_config,
        "char_level": char_level,
        "food_type": food_type,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def get_cached_buff_result(session_id: str, input_hash: str):
    """Balikin hasil fase buff yang di-cache, atau None kalau nggak ada/basi."""
    key = f"{session_id}:{input_hash}"
    with _lock:
        entry = _cache.get(key)
        if not entry:
            return None
        if time.time() - entry["stored_at"] > CACHE_TTL_SECONDS:
            del _cache[key]
            return None
        return entry["result"]


def set_cached_buff_result(session_id: str, input_hash: str, result: dict):
    """Simpan hasil fase buff. Otomatis replace kalau session_id yang sama
    submit ulang (regenerate) — nggak ada akumulasi entry lama."""
    key = f"{session_id}:{input_hash}"
    with _lock:
        # Buang entry lama punya session_id ini yang hash-nya beda (ganti
        # skill/equipment/battle_config fase buff -> otomatis stale, dibuang)
        stale_keys = [k for k in _cache if k.startswith(f"{session_id}:") and k != key]
        for k in stale_keys:
            del _cache[k]
        _cache[key] = {"result": result, "stored_at": time.time()}


def _purge_expired():
    """Housekeeping opsional — buang entry expired dari session mana pun."""
    now = time.time()
    with _lock:
        expired = [k for k, v in _cache.items() if now - v["stored_at"] > CACHE_TTL_SECONDS]
        for k in expired:
            del _cache[k]
