"""
Verifier: pastikan semua modul .py di project bisa di-import tanpa
ImportError/NameError/dsb. Auto-discovery dari filesystem — GAK
hardcode daftar modul, jadi otomatis ngikutin kalau ada file
baru/pindah pas refactor.
"""
import importlib

import pytest

from tests._ast_utils import ROOT, is_excluded


def _is_test_or_private(path):
    stem = path.stem
    return stem.startswith("_") or stem.startswith("test_")


def _is_valid_module_path(path):
    """Skip path yang gak mungkin jadi nama modul Python valid (mis. ada dash di folder)."""
    rel = path.relative_to(ROOT).with_suffix("")
    return all(part.isidentifier() for part in rel.parts)


def _path_to_module_name(path):
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def _discover_modules():
    modules = []
    for path in ROOT.rglob("*.py"):
        if is_excluded(path):
            continue
        if _is_test_or_private(path):
            continue
        if not _is_valid_module_path(path):
            continue
        modules.append(_path_to_module_name(path))
    return sorted(modules)


MODULES = _discover_modules()


def test_modules_were_discovered():
    # sanity check — kalau ini kosong, parametrize di bawah gak collect
    # test sama sekali dan verifier jadi "buta" (diam-diam selalu hijau)
    assert MODULES, "Auto-discovery gak nemu modul apapun — cek ROOT/exclude rules di _ast_utils.py"


@pytest.mark.parametrize("module_name", MODULES)
def test_module_importable(module_name):
    try:
        importlib.import_module(module_name)
    except Exception as e:
        pytest.fail(f"Import gagal: {module_name} -> {type(e).__name__}: {e}")
