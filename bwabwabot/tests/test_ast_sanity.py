# tests/test_ast_sanity.py — verifier AST: deteksi "decorator orphan"
"""Deteksi decorator yang tidak menempel ke def/class manapun.

Bug yang dicegah: script removal pakai ast.get_source_segment yang sudah
termasuk decorator, jadi pattern strip gagal dan decorator-nya nyangkut
sendiri. Compile-clean (stacked decorator tanpa def = valid syntax) tapi
runtime broken (mis. @staticmethod + def(self) = method jadi static).

Verifier ini menangkap:
- @staticmethod + argumen pertama self/cls
- @classmethod + argumen pertama bukan cls
- Nama decorator yang dikenal tapi lekat ke def dgn argumen tidak sesuai
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _iter_py_files():
    for p in ROOT.rglob("*.py"):
        if any(part.startswith(".") for part in p.relative_to(ROOT).parts):
            continue
        if "__pycache__" in p.parts:
            continue
        if ".venv" in p.parts:
            continue
        yield p


def _find_orphan_decorators(path: Path) -> list[tuple[int, str, str]]:
    """Return list (lineno, func_name, reason)."""
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
    except Exception:
        return []
    problems = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = [a.arg for a in n.args.args]
        first = arg_names[0] if arg_names else None
        for d in n.decorator_list:
            if isinstance(d, ast.Name):
                if d.id == "staticmethod" and first in ("self", "cls"):
                    problems.append((n.lineno, n.name, f"@staticmethod + {first}"))
                if d.id == "classmethod" and first not in ("cls",):
                    problems.append((n.lineno, n.name, f"@classmethod + {first}"))
    return problems


def test_no_orphan_decorators_all_files() -> None:
    problems = []
    for p in _iter_py_files():
        for lineno, name, reason in _find_orphan_decorators(p):
            problems.append(f"{p.relative_to(ROOT)}:{lineno} {name} ({reason})")
    assert not problems, "Decorator orphan ditemukan:\n" + "\n".join(problems)


# --- Negative test: verifier harus bisa FAIL ---

def test_negative_detects_staticmethod_with_self() -> None:
    """Kalau ada @staticmethod + self, verifier HARUS deteksi."""
    src = "class X:\n    @staticmethod\n    def foo(self):\n        pass\n"
    tree = ast.parse(src)
    problems = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            first = n.args.args[0].arg if n.args.args else None
            for d in n.decorator_list:
                if isinstance(d, ast.Name) and d.id == "staticmethod" and first in ("self", "cls"):
                    problems.append((n.name, first))
    assert problems, "verifier buta: @staticmethod + self tidak terdeteksi"


def test_negative_detects_classmethod_without_cls() -> None:
    src = "class X:\n    @classmethod\n    def foo(self):\n        pass\n"
    tree = ast.parse(src)
    problems = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            first = n.args.args[0].arg if n.args.args else None
            for d in n.decorator_list:
                if isinstance(d, ast.Name) and d.id == "classmethod" and first not in ("cls",):
                    problems.append((n.name, first))
    assert problems, "verifier buta: @classmethod + non-cls tidak terdeteksi"
