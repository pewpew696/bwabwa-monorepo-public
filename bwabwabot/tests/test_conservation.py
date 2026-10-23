"""
Verifier: pastikan tiap definisi (top-level function/class/method/
konstanta module-level) yang dicatat di baseline (tests/baselines/*.json)
tetap ada di project.

v1: cek (kind, name) ADA tepat 1 tempat.

v2 — dukung "transformasi terdokumentasi" (staticmethod jadi free
function, dsb) lewat field opsional `transform` di entry baseline.

Logika buat entry ber-transform (INVERSE CHECK, 2 kondisi independen):
  1. Lokasi ASAL (entry.file, entry.kind, entry.name) WAJIB SUDAH GAK
     ADA lagi di situ -> kalau masih ada = FAIL "pindah tidak tuntas".
  2. Lokasi TARGET (transform.to_file, to_kind, to_name) WAJIB ADA
     tepat 1 tempat di file yang didokumentasikan.
Entry TANPA transform: perilaku v1 (ada tepat 1 tempat, di manapun).

Baseline lama tanpa field `transform` tetap valid (backward compatible).
"""
import json
from pathlib import Path

import pytest

from tests._ast_utils import ROOT, iter_project_py_files, top_level_defs

BASELINES_DIR = Path(__file__).resolve().parent / "baselines"

_REQUIRED_TRANSFORM_FIELDS = {"reason", "to_file", "to_kind", "to_name"}


def _build_project_index():
    """(kind, name) -> list file relatif yang punya definisi itu sekarang."""
    index = {}
    for path in iter_project_py_files():
        rel = str(path.relative_to(ROOT))
        for kind, name in top_level_defs(path):
            index.setdefault((kind, name), []).append(rel)
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


def _check_entries(entries, index):
    """
    Return list pesan error (kosong = semua OK). Sengaja dipisah dari
    body test biar bisa dites pakai index/entries SINTETIS.
    """
    problems = []
    for entry in entries:
        transform = entry.get("transform")

        if transform:
            # Validasi field wajib (kalau hilang -> FAIL informatif)
            missing = _REQUIRED_TRANSFORM_FIELDS - set(transform.keys())
            if missing:
                problems.append(
                    f"TRANSFORM-INVALID: {entry['kind']} '{entry['name']}' "
                    f"(@ {entry['file']}) transform kurang field: {sorted(missing)}"
                )
                continue

            # 1) INVERSE CHECK — lokasi asal wajib SUDAH GAK ADA
            original_key = (entry["kind"], entry["name"])
            original_locations = index.get(original_key, [])
            if entry["file"] in original_locations:
                problems.append(
                    f"INVERSE-FAIL: {entry['kind']} '{entry['name']}' masih ada di "
                    f"lokasi asal {entry['file']} — harusnya sudah dipindah/dihapus "
                    f"dari sana (transform: {transform.get('reason', '?')})"
                )

            # 2) target WAJIB ada tepat 1 tempat di file yang didokumentasikan
            target_key = (transform["to_kind"], transform["to_name"])
            target_locations = index.get(target_key, [])
            if len(target_locations) == 0:
                problems.append(
                    f"TRANSFORM-TARGET-HILANG: {transform['to_kind']} "
                    f"'{transform['to_name']}' (target transform dari {entry['kind']} "
                    f"'{entry['name']}' @ {entry['file']}) gak ketemu di manapun"
                )
            elif len(target_locations) >= 2:
                problems.append(
                    f"TRANSFORM-TARGET-DUPLIKAT: {transform['to_kind']} "
                    f"'{transform['to_name']}' muncul di {target_locations} "
                    f"(harusnya cuma 1 tempat)"
                )
            elif transform["to_file"] not in target_locations:
                problems.append(
                    f"TRANSFORM-TARGET-SALAH-FILE: {transform['to_kind']} "
                    f"'{transform['to_name']}' ketemu di {target_locations}, tapi "
                    f"bukan di {transform['to_file']} yang didokumentasikan di baseline"
                )
        else:
            key = (entry["kind"], entry["name"])
            locations = index.get(key, [])
            if len(locations) == 0:
                problems.append(
                    f"HILANG: {entry['kind']} '{entry['name']}' "
                    f"(asal: {entry['file']}) gak ketemu di manapun"
                )
            elif len(locations) >= 2:
                # duplicate_allowed=True: duplikat sengaja (copy per modul
                # untuk isolasi). Field wajib disertai 'duplicate_reason'.
                if entry.get("duplicate_allowed"):
                    reason = entry.get("duplicate_reason")
                    if not reason:
                        problems.append(
                            f"DUPLICATE-REASON-KURANG: {entry['kind']} '{entry['name']}' "
                            f"(asal: {entry['file']}) punya duplicate_allowed tapi tanpa "
                            f"duplicate_reason"
                        )
                else:
                    problems.append(
                        f"DUPLIKAT: {entry['kind']} '{entry['name']}' "
                        f"(asal: {entry['file']}) muncul di {locations}"
                    )
    return problems


def test_conservation_semua_baseline():
    entries = _load_all_baselines()
    if not entries:
        pytest.skip("belum ada baseline di tests/baselines/ — jalankan update_baseline.py dulu")
    index = _build_project_index()
    problems = _check_entries(entries, index)
    assert not problems, "Konservasi gagal:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# Negative test bawaan (WAJIB) — mastiin verifier ini beneran bisa FAIL.
# Semua pakai index/entries SINTETIS, gak scan project asli.
# ---------------------------------------------------------------------------

def test_verifier_bisa_fail_kalau_nama_hilang():
    fake_index = {("function", "_fmt_price"): ["cogs/economy/base.py"]}
    fake_entries = [
        {"file": "cogs/economy/base.py", "kind": "function", "name": "_fmt_price"},
        {"file": "cogs/economy/base.py", "kind": "function", "name": "_nama_sengaja_dihilangkan"},
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert any("HILANG" in p for p in problems), "Verifier gagal mendeteksi nama yang hilang!"


def test_verifier_bisa_fail_kalau_nama_duplikat():
    fake_index = {
        ("function", "_fmt_price"): ["cogs/economy/base.py", "cogs/economy/market/prices.py"],
    }
    fake_entries = [{"file": "cogs/economy/base.py", "kind": "function", "name": "_fmt_price"}]
    problems = _check_entries(fake_entries, fake_index)
    assert any("DUPLIKAT" in p for p in problems), "Verifier gagal mendeteksi duplikat!"


def test_verifier_bisa_fail_kalau_method_duplikat():
    """Method (qualified name) yang ke-duplikat juga wajib kedetect."""
    fake_index = {
        ("staticmethod", "FairPriceCommands._fp_spread_pct"): [
            "cogs/economy/fairprice.py",
            "services/economy/fairprice_market.py",
        ],
    }
    fake_entries = [
        {"file": "cogs/economy/fairprice.py", "kind": "staticmethod",
         "name": "FairPriceCommands._fp_spread_pct"},
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert any("DUPLIKAT" in p for p in problems), "Verifier gagal mendeteksi method duplikat!"


def test_verifier_bisa_fail_kalau_konstanta_hilang():
    """Konstanta module-level yang hilang total dari project wajib kedetect."""
    fake_index = {}
    fake_entries = [
        {"file": "cogs/economy/fairprice.py", "kind": "constant", "name": "SPREAD_HEALTHY_MAX"},
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert any("HILANG" in p for p in problems), "Verifier gagal mendeteksi konstanta hilang!"


def test_verifier_bisa_fail_kalau_transform_target_hilang():
    """Entry ber-transform tapi target-nya gak ketemu di manapun -> FAIL."""
    fake_index = {}
    fake_entries = [
        {
            "file": "cogs/economy/fairprice.py",
            "kind": "staticmethod",
            "name": "FairPriceCommands._fp_spread_pct",
            "transform": {
                "reason": "staticmethod di class -> fungsi modul",
                "to_file": "services/economy/fairprice_market.py",
                "to_kind": "function",
                "to_name": "_fp_spread_pct",
            },
        },
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert any("TRANSFORM-TARGET-HILANG" in p for p in problems), (
        "Verifier gagal mendeteksi target transform yang hilang!"
    )


def test_verifier_bisa_fail_kalau_inverse_check_original_masih_ada():
    """
    Entry ber-transform, target SUDAH ada, tapi lokasi asal MASIH ADA
    (pindah gak tuntas) -> WAJIB FAIL lewat inverse check.
    """
    fake_index = {
        ("function", "_fp_spread_pct"): ["services/economy/fairprice_market.py"],
        ("staticmethod", "FairPriceCommands._fp_spread_pct"): ["cogs/economy/fairprice.py"],
    }
    fake_entries = [
        {
            "file": "cogs/economy/fairprice.py",
            "kind": "staticmethod",
            "name": "FairPriceCommands._fp_spread_pct",
            "transform": {
                "reason": "staticmethod di class -> fungsi modul",
                "to_file": "services/economy/fairprice_market.py",
                "to_kind": "function",
                "to_name": "_fp_spread_pct",
            },
        },
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert any("INVERSE-FAIL" in p for p in problems), (
        "Verifier gagal mendeteksi lokasi asal yang masih ada!"
    )
    assert not any("TARGET-HILANG" in p for p in problems), (
        "False positive: target sebenarnya ada"
    )


def test_verifier_bisa_fail_kalau_transform_target_duplikat():
    """Target transform muncul di 2 tempat -> FAIL (bukan cuma cek 'to_file ada')."""
    fake_index = {
        ("function", "_fp_spread_pct"): [
            "services/economy/fairprice_market.py",
            "services/economy/other.py",
        ],
    }
    fake_entries = [
        {
            "file": "cogs/economy/fairprice.py",
            "kind": "staticmethod",
            "name": "FairPriceCommands._fp_spread_pct",
            "transform": {
                "reason": "staticmethod -> fungsi modul",
                "to_file": "services/economy/fairprice_market.py",
                "to_kind": "function",
                "to_name": "_fp_spread_pct",
            },
        },
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert any("TRANSFORM-TARGET-DUPLIKAT" in p for p in problems), (
        "Verifier gagal mendeteksi target duplikat!"
    )


def test_verifier_bisa_fail_kalau_transform_field_kurang():
    """Entry ber-transform tapi field wajib kurang -> FAIL informatif, bukan KeyError."""
    fake_index = {
        ("function", "_fp_spread_pct"): ["services/economy/fairprice_market.py"],
    }
    fake_entries = [
        {
            "file": "cogs/economy/fairprice.py",
            "kind": "staticmethod",
            "name": "FairPriceCommands._fp_spread_pct",
            "transform": {
                "reason": "sengaja cuma sebagian",
                "to_file": "services/economy/fairprice_market.py",
                # to_kind & to_name sengaja gak ada
            },
        },
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert any("TRANSFORM-INVALID" in p for p in problems), (
        "Verifier gagal mendeteksi transform field yang kurang!"
    )


def test_verifier_transform_valid_tidak_false_positive():
    """
    Kontrol positif: transform BENAR (original gak ada, target ada tepat
    1 tempat) -> problems HARUS kosong. Verifier gak boleh selalu-FAIL.
    """
    fake_index = {
        ("function", "_fp_spread_pct"): ["services/economy/fairprice_market.py"],
    }
    fake_entries = [
        {
            "file": "cogs/economy/fairprice.py",
            "kind": "staticmethod",
            "name": "FairPriceCommands._fp_spread_pct",
            "transform": {
                "reason": "staticmethod -> fungsi modul",
                "to_file": "services/economy/fairprice_market.py",
                "to_kind": "function",
                "to_name": "_fp_spread_pct",
            },
        },
    ]
    problems = _check_entries(fake_entries, fake_index)
    assert not problems, f"False positive pada transform valid: {problems}"
