# tests/differential/runner.py — jalankan _fp_analyze, serialize hasil deterministik
"""
Serialisasi hasil _fp_analyze jadi struktur JSON-safe (buat diff).
Prinsip: input sama → output sama. Tidak ada field waktu "sekarang" yang bocor.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from tests.differential.fixture import SAMPLE_CASES, make_cog


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "fp_analyze_snapshots.json"


def _json_safe(value):
    """Konversi nilai jadi JSON-safe (datetime -> iso, deque -> list, dict rekursif)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    # Fallback: coba list (deque?), kalau gagal -> repr string
    try:
        return [_json_safe(v) for v in value]
    except TypeError:
        return {"__type__": type(value).__name__, "value": repr(value)}


async def _run_one(case: dict) -> dict:
    """Jalankan satu case, return {case_id, item, orderbook, result}."""
    cog_kwargs = case.get("_cog_kwargs", {})
    cog = make_cog(**cog_kwargs)
    result = await cog._fp_analyze(case["item"], case["orderbook"])
    return {
        "id": case["id"],
        "item": case["item"],
        "orderbook": _json_safe(case["orderbook"]),
        "result": _json_safe(result),
    }


def run_all() -> list[dict]:
    """Jalankan semua SAMPLE_CASES, return list snapshot (JSON-safe)."""
    async def _main():
        return [await _run_one(c) for c in SAMPLE_CASES]
    return asyncio.run(_main())


def save_snapshot(path: Path | None = None) -> Path:
    """Generate snapshot dari kode SEKARANG, tulis ke fixture JSON."""
    path = path or FIXTURE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = run_all()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_snapshot(path: Path | None = None) -> list[dict]:
    """Load fixture JSON."""
    path = path or FIXTURE_PATH
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    out = save_snapshot()
    print(f"Snapshot saved: {out}")
    print(f"Total cases: {len(run_all())}")
