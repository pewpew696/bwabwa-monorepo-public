"""
Helper bareng buat verifier tests. Bukan test itu sendiri — sengaja
diawali underscore biar otomatis di-exclude sama auto-discovery
test_imports.py (dan gak ke-collect pytest sebagai test module).

Riwayat:
- v1: def/class/async def top-level doang.
- v2: + method di dalam class (kind method/staticmethod/classmethod/
  async_method/async_staticmethod/async_classmethod) dengan nama
  TERKUALIFIKASI (ClassName.method, nested: Outer.Inner.method).
  PRECEDENCE: async dicek DULU, baru decorator staticmethod/classmethod.
  + konstanta MODULE-LEVEL (Assign & AnnAssign dengan nama UPPERCASE).
  + nested class (rekursif).
  + property collapse: getter/setter/deleter dengan nama sama -> 1 entry
    (kind "property" atau "async_property").
  Konstanta di DALAM class (class-level attribute) SENGAJA TIDAK di-track.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIR_NAMES = {"venv", "__pycache__", ".git", "tests"}
EXCLUDE_DIR_PREFIXES = (".venv",)  # .venv, .venv-test, .venv-test2, dst

_STATICMETHOD_NAMES = {"staticmethod"}
_CLASSMETHOD_NAMES = {"classmethod"}
_PROPERTY_DECOS = {"property", "setter", "deleter", "getter"}


def is_excluded(path: Path) -> bool:
    """True kalau file ini bukan bagian source project asli (venv, backup, dll)."""
    if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
        return True
    if any(part.startswith(EXCLUDE_DIR_PREFIXES) for part in path.parts):
        return True
    if ".bak" in path.name:
        return True
    return False


def iter_project_py_files():
    """Semua .py di project, exclude venv/tests/backup/dsb."""
    for path in ROOT.rglob("*.py"):
        if is_excluded(path):
            continue
        yield path


def _decorator_flat_name(dec):
    """
    Tarik nama 'flat' dari 1 node decorator buat dicocokkan ke
    staticmethod/classmethod/property-setter/dsb.
    Gak resolve import, cuma name-matching sederhana.
    """
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return None


def _decorator_names(node):
    names = set()
    for dec in node.decorator_list:
        name = _decorator_flat_name(dec)
        if name is not None:
            names.add(name)
    return names


def _method_kind(node):
    """PRECEDENCE: cek async DULU, baru decorator staticmethod/classmethod."""
    decs = _decorator_names(node)
    is_async = isinstance(node, ast.AsyncFunctionDef)
    if is_async:
        if decs & _STATICMETHOD_NAMES:
            return "async_staticmethod"
        if decs & _CLASSMETHOD_NAMES:
            return "async_classmethod"
        return "async_method"
    if decs & _STATICMETHOD_NAMES:
        return "staticmethod"
    if decs & _CLASSMETHOD_NAMES:
        return "classmethod"
    return "method"


def _is_constant_name(name) -> bool:
    """UPPERCASE (boleh underscore/digit) = konstanta."""
    return bool(name) and name.isupper()


def _assign_target_names(node):
    """Nama target dari Assign (termasuk tuple/list-unpack & chained) atau AnnAssign."""
    names = []

    def collect(t):
        if isinstance(t, ast.Name):
            names.append(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for el in t.elts:
                collect(el)

    if isinstance(node, ast.Assign):
        for t in node.targets:
            collect(t)
    elif isinstance(node, ast.AnnAssign):
        collect(node.target)
    return names


def _walk_class_body(class_node, out, prefix=""):
    """
    Rekursif ke dalam 1 class:
    - method/staticmethod/classmethod/async_* -> nama TERKUALIFIKASI
    - property (getter+setter+deleter nama sama) -> collapse ke 1 entry
    - nested class -> rekursif dengan prefix yang benar (Outer.Inner)
    Class-level constant/attribute biasa SENGAJA dilewati.
    """
    class_path = f"{prefix}.{class_node.name}" if prefix else class_node.name

    # Deteksi nama properti (method dengan decorator property-related)
    property_names = set()
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decos = _decorator_names(item)
            if decos & _PROPERTY_DECOS:
                property_names.add(item.name)

    seen_properties = set()
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = f"{class_path}.{item.name}"
            if item.name in property_names:
                if item.name in seen_properties:
                    continue
                seen_properties.add(item.name)
                is_async = isinstance(item, ast.AsyncFunctionDef)
                out.append(("async_property" if is_async else "property", qualified))
                continue
            out.append((_method_kind(item), qualified))
        elif isinstance(item, ast.ClassDef):
            out.append(("class", f"{class_path}.{item.name}"))
            _walk_class_body(item, out, prefix=class_path)


def top_level_defs_from_source(source_text: str):
    """
    Versi top_level_defs yang nerima source TEXT langsung (bukan path),
    dipakai juga buat baca isi file dari git ref (lihat update_baseline.py
    --from-git) tanpa perlu nulis ke disk dulu.
    """
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append(("function", node.name))
        elif isinstance(node, ast.AsyncFunctionDef):
            out.append(("async_function", node.name))
        elif isinstance(node, ast.ClassDef):
            out.append(("class", node.name))
            _walk_class_body(node, out)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _assign_target_names(node):
                if _is_constant_name(name):
                    out.append(("constant", name))
    return out


def top_level_defs(path: Path):
    """
    List (kind, name) buat definisi yang ditrack verifier konservasi:
    function, async_function, class, method, staticmethod, classmethod,
    async_method, async_staticmethod, async_classmethod, property,
    async_property, constant. AST walk asli (bukan grep substring).
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return top_level_defs_from_source(text)


# =============================================================================
# v3 — Body Conservation (cek BODY byte-identical, bukan cuma struktur/nama)
# =============================================================================
# Ditambahkan sebagai LAYER BARU (tests/test_body_conservation.py), TIDAK
# mengganti apapun di atas.

import copy

_SELF_LIKE_ARG_NAMES = {"self", "cls"}


def _strip_self_arg(args: ast.arguments) -> None:
    """Buang parameter pertama IN-PLACE, HANYA kalau namanya PERSIS self/cls."""
    if args.posonlyargs and args.posonlyargs[0].arg in _SELF_LIKE_ARG_NAMES:
        args.posonlyargs = args.posonlyargs[1:]
        return
    if args.args and args.args[0].arg in _SELF_LIKE_ARG_NAMES:
        args.args = args.args[1:]


def normalize_body(body_node, drop_self: bool = False) -> str:
    """Normalisasi 1 node AST jadi string canonical (AST-identical).
    - FunctionDef/AsyncFunctionDef: decorator dibuang, drop_self -> buang param pertama
      (hanya kalau namanya self/cls).
    - Node lain: dump apa adanya.
    Deepcopy dulu supaya tidak mutate AST asli.
    """
    node = copy.deepcopy(body_node)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.decorator_list = []
        if drop_self:
            _strip_self_arg(node.args)
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _walk_class_body_with_body(class_node, out, prefix=""):
    """Sama seperti _walk_class_body, tapi bawa node AST tiap entry.
    Kind 'class' (nested) dilewati tapi tetap direkursi."""
    class_path = f"{prefix}.{class_node.name}" if prefix else class_node.name
    property_names = set()
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decos = _decorator_names(item)
            if decos & _PROPERTY_DECOS:
                property_names.add(item.name)

    seen_properties = set()
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = f"{class_path}.{item.name}"
            if item.name in property_names:
                if item.name in seen_properties:
                    continue
                seen_properties.add(item.name)
                is_async = isinstance(item, ast.AsyncFunctionDef)
                out.append(("async_property" if is_async else "property", qualified, item))
                continue
            out.append((_method_kind(item), qualified, item))
        elif isinstance(item, ast.ClassDef):
            _walk_class_body_with_body(item, out, prefix=class_path)


def top_level_defs_with_body(source_text: str):
    """Versi top_level_defs_from_source yang juga bawa node AST.
    Return list (kind, name, node). Kind 'class' dilewati total.
    Constant: node = value assignment, bukan Name target.
    """
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append(("function", node.name, node))
        elif isinstance(node, ast.AsyncFunctionDef):
            out.append(("async_function", node.name, node))
        elif isinstance(node, ast.ClassDef):
            _walk_class_body_with_body(node, out)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _assign_target_names(node):
                if _is_constant_name(name):
                    out.append(("constant", name, node.value))
    return out


# =============================================================================
# v4 — Body Transform (extract pure function dari method, cek body conservation
# pakai substitusi + drop_stmt terdokumentasi). Dipakai `tests/test_body_transform.py`
# — verifier TERPISAH, tidak menyentuh v2/v3.
# =============================================================================

def _attr_chain(node):
    """Return tuple ('self','_price_cache') kalau node = chain Name.attr[...], else None."""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.insert(0, cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.insert(0, cur.id)
        return tuple(parts)
    return None


class _SubstituteAttrTransformer(ast.NodeTransformer):
    """Ganti chain Attribute(Name(...), attr...) persis dengan Name(id=target).

    Match persis by tuple chain (mis. ('self','_price_cache')). Tidak resolve import.
    Nested scope (Lambda/FunctionDef/ClassDef di dalam body) TIDAK di-guard —
    untuk use-case project ini tidak ada nested; kalau nanti ada, tambah guard.
    """

    def __init__(self, mapping):
        self.mapping = {}
        for k, v in mapping.items():
            self.mapping[tuple(k.split("."))] = v

    def visit_Attribute(self, node):
        self.generic_visit(node)
        chain = _attr_chain(node)
        if chain is not None and chain in self.mapping:
            return ast.copy_location(ast.Name(id=self.mapping[chain], ctx=node.ctx), node)
        return node


class _OptionalToPep604Transformer(ast.NodeTransformer):
    """Ubah Subscript(Name('Optional'), slice=X) jadi BinOp(X, BitOr, Constant(None)).

    Konversi `Optional[X]` -> `X | None` (PEP 604).
    """

    def visit_Subscript(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "Optional"
            and isinstance(node.slice, ast.Name)
        ):
            return ast.copy_location(
                ast.BinOp(
                    left=ast.Name(id=node.slice.id, ctx=ast.Load()),
                    op=ast.BitOr(),
                    right=ast.Constant(value=None),
                ),
                node,
            )
        return node


def _drop_stmts_from_body(func_node, drop_sources):
    """Hapus statement di func_node.body yang AST-match dengan `drop_sources` (list source str)."""
    if not drop_sources:
        return
    try:
        drop_nodes = [ast.parse(s).body[0] for s in drop_sources]
    except SyntaxError as exc:
        raise ValueError(f"drop_stmt tidak valid sebagai statement: {exc}") from exc
    drop_dumps = {ast.dump(n) for n in drop_nodes}
    func_node.body = [s for s in func_node.body if ast.dump(s) not in drop_dumps]


def apply_body_transform(node, transform):
    """Apply transform {'substitute': {...}, 'drop_stmt': [...]} ke deepcopy node.

    Return node baru. Node asli TIDAK di-mutate.
    """
    new_node = copy.deepcopy(node)
    transform = transform or {}
    subs = transform.get("substitute") or {}
    drops = transform.get("drop_stmt") or []
    target_args = transform.get("target_args")
    annotation_style = transform.get("annotation_style")

    if annotation_style == "pep604":
        new_node = _OptionalToPep604Transformer().visit(new_node)
    elif annotation_style is not None:
        raise ValueError(f"annotation_style '{annotation_style}' tidak dikenal (hanya 'pep604')")

    # URUTAN: drop dulu (match source asli pre-substitute), baru substitute.
    if drops:
        if not isinstance(new_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise ValueError(f"drop_stmt hanya support FunctionDef/AsyncFunctionDef, dapat {type(new_node).__name__}")
        _drop_stmts_from_body(new_node, drops)

    if subs:
        new_node = _SubstituteAttrTransformer(subs).visit(new_node)

    # Rewrite nama fungsi ke target (body_normalized menyimpan FunctionDef.name)
    target_name = transform.get("target_name")
    if target_name is not None:
        if not isinstance(new_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise ValueError(f"target_name hanya support FunctionDef/AsyncFunctionDef")
        new_node.name = target_name

    if target_args is not None:
        if not isinstance(new_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raise ValueError(f"target_args hanya support FunctionDef/AsyncFunctionDef, dapat {type(new_node).__name__}")
        # target_args = source string persis isi tanda kurung (mis. "cache, exclude=None")
        try:
            parsed = ast.parse(f"def _f({target_args}): pass")
        except SyntaxError as exc:
            raise ValueError(f"target_args tidak valid: {exc}") from exc
        new_node.args = parsed.body[0].args

    return new_node
