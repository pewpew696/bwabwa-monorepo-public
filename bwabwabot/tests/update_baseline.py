"""
Regenerate baseline JSON buat satu file sumber (dipanggil manual,
BUKAN bagian dari test suite).

Usage:
    python3 tests/update_baseline.py cogs/economy/base.py
    python3 tests/update_baseline.py cogs/economy/fairprice.py --from-git pre-tahap2-fairprice
    python3 tests/update_baseline.py cogs/economy/fairprice.py --from-git pre-tahap2-fairprice --with-body

--from-git <ref>: ambil isi file dari tag/commit/branch itu (lewat
`git show <ref>:<path>`, dijalankan dari root project) alih-alih dari
working tree. Berguna buat generate baseline dari versi SEBELUM
ekstraksi, walau file itu di working tree sekarang udah beda/hilang.

--with-body: simpan juga field 'body_normalized' di tiap entry (buat
verifier body-conservation v3, tests/test_body_conservation.py).
Default TIDAK (backward compat — baseline lama tetap valid tanpa field ini).

Field `transform` di baseline TIDAK dibikin otomatis — itu keputusan
manual manusia. Format:
    {
      "file": "cogs/economy/fairprice.py",
      "kind": "staticmethod",
      "name": "FairPriceCommands._fp_spread_pct",
      "transform": {
        "reason": "staticmethod di class -> fungsi modul",
        "to_file": "services/economy/fairprice_market.py",
        "to_kind": "function",
        "to_name": "_fp_spread_pct"
      }
    }

Preserve transform: kalau baseline lama untuk file yang sama sudah
punya entry ber-transform, regenerate berikutnya bakal preserve
field itu untuk entry dengan (kind, name) SAMA PERSIS.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._ast_utils import (
    ROOT,
    top_level_defs_from_source,
    top_level_defs_with_body,
    normalize_body,
)

BASELINES_DIR = Path(__file__).resolve().parent / "baselines"

_REQUIRED_TRANSFORM_FIELDS = {"reason", "to_file", "to_kind", "to_name"}


def _validate_transform_fields(entries):
    """Entry dengan 'transform' WAJIB punya semua field wajib."""
    errors = []
    for e in entries:
        t = e.get("transform")
        if t is None:
            continue
        missing = _REQUIRED_TRANSFORM_FIELDS - set(t.keys())
        if missing:
            errors.append(
                f"Entry {e.get('kind')} '{e.get('name')}' punya transform tapi field "
                f"wajib kurang: {sorted(missing)}"
            )
    return errors


def _fetch_from_git(ref: str, rel_path: str) -> str:
    """Ambil isi file dari commit/tag/branch via `git show <ref>:<path>`.
    Gagal -> exit rapi dengan stderr git apa adanya, BUKAN except: pass."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"git show gagal (exit {result.returncode}) buat '{ref}:{rel_path}':")
        print(result.stderr.strip())
        sys.exit(1)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(
        description="Regenerate baseline JSON dari satu file sumber."
    )
    parser.add_argument("path", help="path relatif file sumber dari root project")
    parser.add_argument(
        "--from-git",
        metavar="REF",
        help="ambil isi file dari tag/commit/branch ini, bukan dari working tree",
    )
    parser.add_argument(
        "--with-body",
        action="store_true",
        help=(
            "simpan field 'body_normalized' di tiap entry (verifier v3). "
            "Default: TIDAK (backward compat)."
        ),
    )
    args = parser.parse_args()

    rel_path = args.path
    if args.from_git:
        source_text = _fetch_from_git(args.from_git, rel_path)
    else:
        src_path = ROOT / rel_path
        if not src_path.exists():
            print(f"File gak ketemu: {src_path}")
            sys.exit(1)
        try:
            source_text = src_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print(f"Gagal baca {src_path}: {exc}")
            sys.exit(1)

    defs = top_level_defs_from_source(source_text)

    if not defs:
        print(f"Peringatan: {rel_path} gak punya definisi yang kedetect.")

    entries = [{"file": rel_path, "kind": kind, "name": name} for kind, name in defs]

    if args.with_body:
        # Body diambil dari SOURCE yang sedang di-parse (working tree atau
        # --from-git <ref>) — otomatis jadi "body asal" kalau ref-nya sebelum
        # ekstraksi. Transform tetap manual di JSON.
        body_map = {
            (kind, name): normalize_body(node, drop_self=True)
            for kind, name, node in top_level_defs_with_body(source_text)
        }
        for e in entries:
            key = (e["kind"], e["name"])
            if key in body_map:
                e["body_normalized"] = body_map[key]

    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    out_name = rel_path.replace("/", "_")[:-3] + ".json"
    out_path = BASELINES_DIR / out_name

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        existing_transforms = {
            (e["kind"], e["name"]): e["transform"] for e in existing if e.get("transform")
        }
        existing_duplicates = {
            (e["kind"], e["name"]): (
                e.get("duplicate_allowed"), e.get("duplicate_reason"),
            )
            for e in existing if e.get("duplicate_allowed")
        }
        for e in entries:
            key = (e["kind"], e["name"])
            if key in existing_transforms:
                e["transform"] = existing_transforms[key]
            if key in existing_duplicates:
                allowed, reason = existing_duplicates[key]
                e["duplicate_allowed"] = allowed
                if reason is not None:
                    e["duplicate_reason"] = reason

    errors = _validate_transform_fields(entries)
    if errors:
        print("Validasi transform gagal:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Baseline tersimpan: {out_path} ({len(entries)} entry)")


if __name__ == "__main__":
    main()
