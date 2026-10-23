"""
Verifier BARU (v3) — cek BODY AST-normalized, bukan cuma struktur/nama
seperti test_conservation.py (v2). LAYER TAMBAHAN, BUKAN pengganti v2.

Kenapa perlu: v2 cuma cek "definisi (kind,name) ada di manapun". Kalau
body-nya diubah 1 karakter (mis. `>` jadi `>=`), v2 tetap PASS. v3
nutup celah itu dengan bandingin body AST-normalized current vs
`body_normalized` yang disimpan di baseline.

Field `body_normalized` OPSIONAL di entry baseline:
- ADA -> body-nya dicek di sini.
- TIDAK ADA (baseline lama, belum di-upgrade) -> SKIP entry (bukan FAIL).
  Ini backward-compat wajib.

Logika cek (entry TANPA transform):
    Body dibandingkan terhadap lokasi TUNGGAL dari (kind, name) di
    project — TIDAK peduli file-nya sama atau beda dari `entry["file"]`.
    v2 sudah jamin "ada tepat 1 tempat", jadi v3 tinggal compare body.
    (Ini fix bug v3 awal: entry pindah same-kind tanpa transform —
    mis. `_short_name` pindah dari cogs/ ke services/ — tetap PASS
    kalau body identik.)

Logika cek (entry DENGAN transform):
    Body current di lokasi TARGET (transform.to_file/to_kind/to_name)
    dibandingkan dengan body_normalized dari versi ASAL.

drop_self=True dipakai KE DUA SISI secara konsisten. Aman dipanggil
ke fungsi yang parameter pertamanya bukan self/cls (normalize_body
cuma motong kalau namanya PERSIS "self" atau "cls").

Keterbatasan: property setter/deleter TIDAK dibandingkan (cuma getter);
dynamic code (exec/eval) di luar jangkauan (AST statis).
"""
import json
from pathlib import Path

import pytest

from tests._ast_utils import (
    ROOT,
    iter_project_py_files,
    top_level_defs_with_body,
    normalize_body,
)

BASELINES_DIR = Path(__file__).resolve().parent / "baselines"


def _build_body_index():
    """(kind, name) -> list of (rel_file, normalized_body) untuk semua definisi project SEKARANG."""
    index = {}
    for path in iter_project_py_files():
        rel = str(path.relative_to(ROOT))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for kind, name, node in top_level_defs_with_body(text):
            normalized = normalize_body(node, drop_self=True)
            index.setdefault((kind, name), []).append((rel, normalized))
    return index


def _load_all_baselines():
    entries = []
    if not BASELINES_DIR.exists():
        return entries
    for jf in sorted(BASELINES_DIR.glob("*.json")):
        if jf.name.startswith("_"):
            continue  # file meta (mis. _body_transforms.json), bukan baseline konservasi
        entries.extend(json.loads(jf.read_text(encoding="utf-8")))
    return entries


def _check_body_entries(entries, index):
    """
    Return (problems, skipped). Sengaja dipisah dari body test biar bisa
    dites pakai index/entries SINTETIS.
    `index`: (kind, name) -> list of (file, normalized_body).
    """
    problems = []
    skipped = 0

    for entry in entries:
        if "body_normalized" not in entry:
            skipped += 1
            continue

        expected = entry["body_normalized"]
        transform = entry.get("transform")

        if transform:
            # Cek target transform — file HARUS persis to_file
            target_key = (transform["to_kind"], transform["to_name"])
            locations = index.get(target_key, [])
            matches = [body for (f, body) in locations if f == transform["to_file"]]
            if not matches:
                problems.append(
                    f"BODY-TARGET-HILANG: {transform['to_kind']} '{transform['to_name']}' "
                    f"(target transform dari {entry['kind']} '{entry['name']}' @ "
                    f"{entry['file']}) gak ketemu di {transform['to_file']}"
                )
                continue
            current_body = matches[0]
            if current_body != expected:
                problems.append(
                    f"BODY-BERUBAH (transform): {transform['to_kind']} "
                    f"'{transform['to_name']}' @ {transform['to_file']} -- body gak "
                    f"sama persis dengan versi asal ({entry['kind']} '{entry['name']}' "
                    f"@ {entry['file']})"
                )
        else:
            # FIX: TIDAK cek entry.file — pindah same-kind (file beda,
            # tanpa transform) tetap valid. Cukup lihat (kind, name)
            # tunggal yang dijamin v2.
            key = (entry["kind"], entry["name"])
            locations = index.get(key, [])
            if not locations:
                problems.append(
                    f"BODY-TARGET-HILANG: {entry['kind']} '{entry['name']}' "
                    f"(asal: {entry['file']}) gak ketemu di manapun"
                )
                continue
            # Prefer file asal (entry["file"]) kalau ada di locations.
            # Ini handle:
            # 1) Pindah same-kind (file asal tidak ada di locations lagi)
            #    -> fallback ke lokasi tunggal.
            # 2) Duplikat sengaja (duplicate_allowed, file asal MASIH ada)
            #    -> pakai body dari file asal.
            matches_asal = [body for (f, body) in locations if f == entry["file"]]
            if matches_asal:
                current_body = matches_asal[0]
            else:
                current_body = locations[0][1]
            if current_body != expected:
                problems.append(
                    f"BODY-BERUBAH: {entry['kind']} '{entry['name']}' "
                    f"(asal: {entry['file']}, sekarang di {locations[0][0]}) -- "
                    f"body gak sama persis dengan baseline"
                )

    return problems, skipped


def test_body_conservation_semua_baseline():
    entries = _load_all_baselines()
    if not entries:
        pytest.skip("belum ada baseline di tests/baselines/ — jalankan update_baseline.py dulu")
    index = _build_body_index()
    problems, _skipped = _check_body_entries(entries, index)
    assert not problems, "Body conservation gagal:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# Negative test (WAJIB) — input SINTETIS, terbukti bisa FAIL.
# ---------------------------------------------------------------------------

def _first_top_level_node(source: str):
    import ast as _ast
    return _ast.parse(source).body[0]


def test_body_bisa_fail_kalau_operator_diubah():
    """Body diubah 1 operator (`>` -> `>=`) -> WAJIB FAIL."""
    original_src = "def f(x):\n    if x > 10:\n        return True\n    return False\n"
    changed_src  = "def f(x):\n    if x >= 10:\n        return True\n    return False\n"

    baseline_body = normalize_body(_first_top_level_node(original_src), drop_self=True)
    fake_entries = [
        {"file": "pkg/mod.py", "kind": "function", "name": "f", "body_normalized": baseline_body},
    ]
    fake_index = {
        ("function", "f"): [
            ("pkg/mod.py", normalize_body(_first_top_level_node(changed_src), drop_self=True)),
        ],
    }
    problems, skipped = _check_body_entries(fake_entries, fake_index)
    assert skipped == 0
    assert any("BODY-BERUBAH" in p for p in problems), "Verifier gagal deteksi operator diubah!"


def test_body_bisa_fail_kalau_konstanta_literal_diubah():
    """Body diubah 1 konstanta (`25.0` -> `26.0`) -> WAJIB FAIL."""
    original_src = "def f(cost_info, pp_value):\n    score = 25.0\n    return score\n"
    changed_src  = "def f(cost_info, pp_value):\n    score = 26.0\n    return score\n"

    baseline_body = normalize_body(_first_top_level_node(original_src), drop_self=True)
    fake_entries = [
        {"file": "pkg/mod.py", "kind": "function", "name": "f", "body_normalized": baseline_body},
    ]
    fake_index = {
        ("function", "f"): [
            ("pkg/mod.py", normalize_body(_first_top_level_node(changed_src), drop_self=True)),
        ],
    }
    problems, skipped = _check_body_entries(fake_entries, fake_index)
    assert skipped == 0
    assert any("BODY-BERUBAH" in p for p in problems), "Verifier gagal deteksi konstanta diubah!"


def test_body_transform_sama_pass_kontrol_positif():
    """Transform method->function, body IDENTIK -> PASS (kontrol positif)."""
    import ast as _ast

    method_src = (
        "class C:\n"
        "    def _fp_model_confidence(self, cost_info, pp_value):\n"
        "        score = 25.0\n"
        "        return score\n"
    )
    function_src = (
        "def _fp_model_confidence(cost_info, pp_value):\n"
        "    score = 25.0\n"
        "    return score\n"
    )
    method_node = _ast.parse(method_src).body[0].body[0]
    function_node = _ast.parse(function_src).body[0]

    baseline_body = normalize_body(method_node, drop_self=True)
    fake_entries = [
        {
            "file": "cogs/economy/fairprice.py",
            "kind": "method",
            "name": "C._fp_model_confidence",
            "body_normalized": baseline_body,
            "transform": {
                "reason": "method -> fungsi modul",
                "to_file": "services/economy/fairprice_reason.py",
                "to_kind": "function",
                "to_name": "_fp_model_confidence",
            },
        },
    ]
    fake_index = {
        ("function", "_fp_model_confidence"): [
            ("services/economy/fairprice_reason.py", normalize_body(function_node, drop_self=True)),
        ],
    }
    problems, skipped = _check_body_entries(fake_entries, fake_index)
    assert skipped == 0
    assert not problems, f"False positive pada transform valid: {problems}"


def test_body_transform_beda_fail():
    """Transform method->function TAPI body beda setelah normalize -> FAIL."""
    import ast as _ast

    method_src = (
        "class C:\n"
        "    def g(self, x):\n"
        "        return x * 2\n"
    )
    function_src_changed = "def g(x):\n    return x * 3\n"
    method_node = _ast.parse(method_src).body[0].body[0]
    function_node = _ast.parse(function_src_changed).body[0]

    baseline_body = normalize_body(method_node, drop_self=True)
    fake_entries = [
        {
            "file": "pkg/mod.py",
            "kind": "method",
            "name": "C.g",
            "body_normalized": baseline_body,
            "transform": {
                "reason": "method -> fungsi modul",
                "to_file": "pkg/target.py",
                "to_kind": "function",
                "to_name": "g",
            },
        },
    ]
    fake_index = {
        ("function", "g"): [("pkg/target.py", normalize_body(function_node, drop_self=True))],
    }
    problems, skipped = _check_body_entries(fake_entries, fake_index)
    assert skipped == 0
    assert any("BODY-BERUBAH" in p for p in problems), "Verifier gagal deteksi body beda!"


def test_body_skip_kalau_baseline_lama_tanpa_body_normalized():
    """Entry tanpa body_normalized (baseline lama) -> SKIP, bukan FAIL."""
    fake_entries = [
        {"file": "cogs/economy/base.py", "kind": "function", "name": "_fmt_price"},
    ]
    fake_index = {}
    problems, skipped = _check_body_entries(fake_entries, fake_index)
    assert not problems, f"Entry tanpa body_normalized harus di-skip: {problems}"
    assert skipped == 1


def test_body_sama_kind_pindah_file_tanpa_transform_pass():
    """
    FIX BUG v3 awal: entry kind=function, baseline file A, current file B,
    body identik, TANPA transform -> HARUS PASS.

    Ini skenario paling umum di project: `_short_name` pindah dari
    cogs/economy/fairprice.py ke services/economy/fairprice_display.py
    tanpa transform (kind tetap "function").
    """
    src = "def _short_name(name):\n    return name[:13]\n"
    baseline_body = normalize_body(_first_top_level_node(src), drop_self=True)
    fake_entries = [
        {
            "file": "cogs/economy/fairprice.py",
            "kind": "function",
            "name": "_short_name",
            "body_normalized": baseline_body,
        },
    ]
    fake_index = {
        ("function", "_short_name"): [
            ("services/economy/fairprice_display.py", baseline_body),
        ],
    }
    problems, skipped = _check_body_entries(fake_entries, fake_index)
    assert skipped == 0
    assert not problems, (
        f"FALSE POSITIVE: pindah same-kind (file beda, tanpa transform) "
        f"dengan body identik harus PASS, tapi dapat: {problems}"
    )


def test_body_updated_tidak_bypass_check():
    """
    Entry dengan field 'body_updated' (dokumentasi: kenapa body beda dari
    pre-refactor) TETAP dicek — body_updated cuma metadata, bukan escape
    hatch. Kalau body_normalized ≠ current, HARUS FAIL walau ada
    body_updated.
    """
    src_ok = "def g(x):\n    return x * 2\n"
    src_changed = "def g(x):\n    return x * 3\n"

    baseline_body = normalize_body(_first_top_level_node(src_ok), drop_self=True)
    fake_entries = [
        {
            "file": "pkg/mod.py",
            "kind": "function",
            "name": "g",
            "body_normalized": baseline_body,
            "body_updated": {
                "reason": "body sengaja diupdate dulu karena call-site",
                "at_commit": "deadbeef",
            },
        },
    ]
    # current body berbeda dari baseline (walau body_updated ada)
    fake_index = {
        ("function", "g"): [
            ("pkg/mod.py", normalize_body(_first_top_level_node(src_changed), drop_self=True)),
        ],
    }
    problems, skipped = _check_body_entries(fake_entries, fake_index)
    assert skipped == 0
    assert any("BODY-BERUBAH" in p for p in problems), (
        "body_updated tidak boleh bypass check — body beda tetap harus FAIL!"
    )
