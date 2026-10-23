"""
Verifier differential — bukti BEHAVIOR (output-based), bukan AST-based.

Target: `_fp_analyze` output identik sebelum vs sesudah refactor.
Baseline: tests/differential/fixtures/fp_analyze_snapshots.json

Cara kerja:
- Jalankan semua SAMPLE_CASES di kode SEKARANG
- Bandingkan hasil dengan snapshot tersimpan
- Kalau ada diff -> FAIL

Test negatif (WAJIB):
- Snapshot diubah 1 field -> FAIL
- Snapshot hilang 1 case -> FAIL
- Snapshot tambah case -> FAIL
- Snapshot kosong -> FAIL (bukan skip)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.differential.runner import FIXTURE_PATH, load_snapshot, run_all


def _compare(expected: list[dict], actual: list[dict]) -> list[str]:
    """Return list problems. Kosong = OK."""
    problems = []

    exp_by_id = {c["id"]: c for c in expected}
    act_by_id = {c["id"]: c for c in actual}

    # Cek jumlah & id set
    if set(exp_by_id.keys()) != set(act_by_id.keys()):
        only_exp = set(exp_by_id) - set(act_by_id)
        only_act = set(act_by_id) - set(exp_by_id)
        if only_exp:
            problems.append(f"CASE-HILANG: {sorted(only_exp)}")
        if only_act:
            problems.append(f"CASE-BARU: {sorted(only_act)}")

    # Bandingkan per-case
    for cid in sorted(set(exp_by_id) & set(act_by_id)):
        exp = exp_by_id[cid]
        act = act_by_id[cid]

        # Orderbook harus identik (input sanity)
        if exp["orderbook"] != act["orderbook"]:
            problems.append(f"INPUT-BERUBAH: {cid}")

        # Result harus identik
        if exp["result"] != act["result"]:
            # Cari field pertama yang beda
            er = exp["result"]
            ar = act["result"]
            if er is None or ar is None:
                problems.append(f"HASIL-BERUBAH: {cid} (None vs non-None)")
            else:
                diff_fields = [k for k in er if er.get(k) != ar.get(k)]
                problems.append(f"HASIL-BERUBAH: {cid} field={diff_fields[:5]}")

    return problems


def test_fp_analyze_differential():
    """Output `_fp_analyze` harus identik dengan snapshot tersimpan."""
    if not FIXTURE_PATH.exists():
        pytest.fail(f"Fixture tidak ada: {FIXTURE_PATH}. Jalankan `python3 -m tests.differential.runner` dulu.")

    expected = load_snapshot()
    actual = run_all()

    assert expected, "Fixture kosong — regenerate snapshot"
    problems = _compare(expected, actual)
    assert not problems, "Differential gagal:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# Negative test (WAJIB) — input SINTETIS, buktikan verifier bisa FAIL
# ---------------------------------------------------------------------------

def _fake_case(cid="x", item="Iron", result=None):
    return {"id": cid, "item": item, "orderbook": None, "result": result or {"recommendation": "HOLD", "current_price": 100.0}}


def test_differential_bisa_fail_kalau_field_berubah():
    """Snapshot field diubah 1 nilai -> WAJIB FAIL."""
    exp = [_fake_case(result={"recommendation": "BUY", "current_price": 100.0})]
    act = [_fake_case(result={"recommendation": "SELL", "current_price": 100.0})]
    problems = _compare(exp, act)
    assert any("HASIL-BERUBAH" in p for p in problems), "Verifier gagal deteksi field berubah!"


def test_differential_bisa_fail_kalau_case_hilang():
    """Snapshot ada case yang hilang -> WAJIB FAIL."""
    exp = [_fake_case("a"), _fake_case("b")]
    act = [_fake_case("a")]
    problems = _compare(exp, act)
    assert any("CASE-HILANG" in p for p in problems), "Verifier gagal deteksi case hilang!"


def test_differential_bisa_fail_kalau_case_baru():
    """Ada case tambahan yang tidak ada di snapshot -> WAJIB FAIL."""
    exp = [_fake_case("a")]
    act = [_fake_case("a"), _fake_case("b")]
    problems = _compare(exp, act)
    assert any("CASE-BARU" in p for p in problems), "Verifier gagal deteksi case baru!"


def test_differential_bisa_fail_kalau_none_berubah_jadi_dict():
    """Result None -> dict -> WAJIB FAIL."""
    exp = [{"id": "x", "item": "Iron", "orderbook": None, "result": None}]
    act = [{"id": "x", "item": "Iron", "orderbook": None, "result": {"recommendation": "HOLD"}}]
    problems = _compare(exp, act)
    assert any("HASIL-BERUBAH" in p for p in problems), "Verifier gagal deteksi None -> dict!"
