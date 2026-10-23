"""
Verifier v4 — body transform (TERPISAH dari v2/v3).

Cek: method/fungsi hasil transform (substitute + drop_stmt terdokumentasi)
di baseline cocok dengan body di working tree.

Kenapa terpisah: v2/v3 tidak handle transform yang mengubah body
(mis. `self._price_cache` -> `price_cache`, `drop_stmt` baris bonus).
Verifier ini khusus handle skenario itu. v2/v3 tidak disentuh.

Baseline: tests/baselines/_body_transforms.json (list entry).
Setiap entry: source_ref (git ref) + transform + target.
"""

import ast
import json
import subprocess
from pathlib import Path

import pytest

from tests._ast_utils import (
    ROOT,
    apply_body_transform,
    iter_project_py_files,
    normalize_body,
    top_level_defs_with_body,
)

BASELINES_PATH = Path(__file__).resolve().parent / "baselines" / "_body_transforms.json"


def _load_transforms():
    if not BASELINES_PATH.exists():
        return []
    return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))


def _git_show(ref, path):
    """Ambil isi file dari git ref. Return None kalau ref/file tidak ada."""
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _find_node_by_qualified(source_text, kind, name):
    """Cari node dari hasil top_level_defs_with_body. Match (kind, name) persis."""
    for k, n, node in top_level_defs_with_body(source_text):
        if k == kind and n == name:
            return node
    return None


def _build_target_index():
    """(rel_file, kind, name) -> normalized body, untuk semua definisi project SEKARANG."""
    index = {}
    for path in iter_project_py_files():
        rel = str(path.relative_to(ROOT))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for kind, name, node in top_level_defs_with_body(text):
            index[(rel, kind, name)] = normalize_body(node, drop_self=True)
    return index


def _check_transform_entries(entries, target_index, git_show_fn):
    """Return list problems. Inject git_show_fn + target_index biar bisa dites sintetis."""
    problems = []
    for entry in entries:
        name = entry.get("name", "<unknown>")

        # 1. Ambil source dari git ref
        src = git_show_fn(entry["source_ref"], entry["source_file"])
        if src is None:
            problems.append(
                f"SOURCE-TIDAK-ADA: '{name}' — file {entry['source_file']} "
                f"tidak ada di ref {entry['source_ref']}"
            )
            continue

        # 2. Cari node source
        src_node = _find_node_by_qualified(src, entry["source_kind"], entry["source_name"])
        if src_node is None:
            problems.append(
                f"SOURCE-NODE-TIDAK-ADA: '{name}' — {entry['source_kind']} "
                f"'{entry['source_name']}' tidak ditemukan di {entry['source_file']} "
                f"@ {entry['source_ref']}"
            )
            continue

        # 3. Apply transform
        try:
            transformed = apply_body_transform(src_node, entry.get("transform"))
        except ValueError as exc:
            problems.append(f"TRANSFORM-INVALID: '{name}' — {exc}")
            continue

        # 4. Normalize hasil transform
        expected_body = normalize_body(transformed, drop_self=True)

        # 5. Ambil body target dari working tree
        target_key = (entry["target_file"], entry["target_kind"], entry["target_name"])
        current_body = target_index.get(target_key)
        if current_body is None:
            problems.append(
                f"TARGET-TIDAK-ADA: '{name}' — {entry['target_kind']} "
                f"'{entry['target_name']}' tidak ditemukan di {entry['target_file']}"
            )
            continue

        # 6. Compare
        if current_body != expected_body:
            problems.append(
                f"BODY-TRANSFORM-BERUBAH: '{name}' — body target "
                f"@ {entry['target_file']} tidak sama dengan body source "
                f"@ {entry['source_ref']} setelah transform"
            )

    return problems


def test_body_transform_semua_baseline():
    entries = _load_transforms()
    if not entries:
        pytest.skip("belum ada entry di tests/baselines/_body_transforms.json")

    target_index = _build_target_index()
    problems = _check_transform_entries(entries, target_index, _git_show)
    assert not problems, "Body transform gagal:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# Negative test (WAJIB) — input SINTETIS, terbukti bisa FAIL.
# ---------------------------------------------------------------------------

def _fake_git_show(files):
    def _show(ref, path):
        return files.get((ref, path))
    return _show


def _fake_target(body_src, file="pkg/target.py", kind="function", name="f"):
    """Bikin target_index sintetis dengan 1 entry."""
    return {(file, kind, name): normalize_body(ast.parse(body_src).body[0], drop_self=True)}


def test_transform_substitute_valid_pass():
    """Substitute self.x -> x, body cocok -> PASS."""
    src = "class C:\n    def f(self):\n        return self._cache.get('a')\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {"substitute": {"self._cache": "cache"}, "drop_stmt": [], "target_args": "cache"},
    }]
    target = _fake_target("def f(cache):\n    return cache.get('a')\n")
    problems = _check_transform_entries(entries, target, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert not problems, f"False positive: {problems}"


def test_transform_substitute_tidak_match_fail():
    """Substitute didefinisikan tapi body target beda -> FAIL."""
    src = "class C:\n    def f(self):\n        return self._cache.get('a')\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {"substitute": {"self._cache": "cache"}, "drop_stmt": []},
    }]
    # Body target masih pakai self._cache -> transform tidak jalan
    target = _fake_target("def f(self):\n    return self._cache.get('a')\n")
    problems = _check_transform_entries(entries, target, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert any("BODY-TRANSFORM-BERUBAH" in p for p in problems), "Verifier gagal deteksi substitute tidak match!"


def test_transform_drop_stmt_valid_pass():
    """drop_stmt match -> baris hilang, body cocok -> PASS."""
    src = "class C:\n    def f(self):\n        x = self._get()\n        return x * 2\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {"substitute": {"self._get": "get"}, "drop_stmt": ["x = self._get()"], "target_args": "get, x"},
    }]
    target = _fake_target("def f(get, x):\n    return x * 2\n")
    problems = _check_transform_entries(entries, target, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert not problems, f"False positive: {problems}"


def test_transform_drop_stmt_tidak_match_fail():
    """drop_stmt didefinisikan tapi baris source beda -> FAIL (baris tetap ada)."""
    src = "class C:\n    def f(self):\n        x = self._get()\n        return x * 2\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {"substitute": {}, "drop_stmt": ["y = 999"]},
    }]
    target = _fake_target("def f(x):\n    return x * 2\n")
    problems = _check_transform_entries(entries, target, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert any("BODY-TRANSFORM-BERUBAH" in p for p in problems), "Verifier gagal deteksi drop_stmt tidak match!"


def test_transform_source_ref_tidak_ada_fail():
    """source_ref tidak ada di git -> FAIL, bukan skip."""
    entries = [{
        "name": "C.f",
        "source_ref": "ref-ngawur", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {},
    }]
    problems = _check_transform_entries(entries, {}, _fake_git_show({}))
    assert any("SOURCE-TIDAK-ADA" in p for p in problems), "Verifier gagal deteksi source ref hilang!"


def test_transform_target_tidak_ada_fail():
    """Target tidak ada di working tree -> FAIL."""
    src = "class C:\n    def f(self):\n        return 1\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/ngawur.py", "target_kind": "function", "target_name": "f",
        "transform": {},
    }]
    problems = _check_transform_entries(entries, {}, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert any("TARGET-TIDAK-ADA" in p for p in problems), "Verifier gagal deteksi target hilang!"

def test_transform_target_args_dengan_default_pass():
    """target_args dengan default value (mis. `cache, exclude=None`) -> PASS."""
    src = "class C:\n    def f(self, exclude=None):\n        return self._cache.get('a')\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {"substitute": {"self._cache": "cache"}, "drop_stmt": [], "target_args": "cache, exclude=None"},
    }]
    target = _fake_target("def f(cache, exclude=None):\n    return cache.get('a')\n")
    problems = _check_transform_entries(entries, target, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert not problems, f"False positive (default arg): {problems}"

def test_transform_annotation_pep604_pass():
    """source Optional[str] -> target str | None via annotation_style='pep604' -> PASS."""
    src = "from typing import Optional\nclass C:\n    def f(self, x: Optional[str] = None):\n        return 1\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {"substitute": {}, "drop_stmt": [], "target_args": "x: str | None = None",
                       "annotation_style": "pep604"},
    }]
    target = _fake_target("def f(x: str | None = None):\n    return 1\n")
    problems = _check_transform_entries(entries, target, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert not problems, f"False positive (pep604): {problems}"


def test_transform_annotation_style_unknown_fail():
    """annotation_style tidak dikenal -> FAIL jujur."""
    src = "class C:\n    def f(self):\n        return 1\n"
    entries = [{
        "name": "C.f",
        "source_ref": "fake", "source_file": "pkg/mod.py",
        "source_kind": "method", "source_name": "C.f",
        "target_file": "pkg/target.py", "target_kind": "function", "target_name": "f",
        "transform": {"substitute": {}, "drop_stmt": [], "annotation_style": "ngawur"},
    }]
    target = _fake_target("def f():\n    return 1\n")
    problems = _check_transform_entries(entries, target, _fake_git_show({("fake", "pkg/mod.py"): src}))
    assert any("TRANSFORM-INVALID" in p for p in problems), "Verifier gagal deteksi annotation_style ngawur!"
