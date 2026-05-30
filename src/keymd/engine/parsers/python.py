"""python.py — Python source parser using the stdlib `ast` module.

Emits language-neutral ParseResult (symbols + edges). Chosen over tree-sitter
for Python because `ast` is zero-dependency, exact, and battle-tested; JS/TS
parsers (Phase 1b) use tree-sitter behind the same Parser interface.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from keymd.engine.parsers.base import Edge, ParseResult, Symbol, register


def _call_name(node) -> str | None:
    """Return 'foo' or 'obj.attr.x' from a Name/Attribute node, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
        return node.attr
    return None


def _signature(node) -> str:
    if isinstance(node, ast.ClassDef):
        # Include keyword bases (e.g. metaclass=Meta), which live in
        # node.keywords, not node.bases — else `class C(metaclass=M)` renders bare.
        parts = [ast.unparse(b) for b in node.bases]
        parts += [ast.unparse(k) for k in node.keywords]
        inner = ", ".join(parts)
        return f"class {node.name}({inner})" if inner else f"class {node.name}"
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{node.name}({args}){ret}"


MAX_VALUE_LEN = 60
_ENUM_BASES = {"Enum", "IntEnum", "StrEnum", "IntFlag", "Flag", "ReprEnum"}


def _is_literal(node) -> bool:
    """True when `node` is a constant the summary can safely show as a value: a
    scalar literal, a (nested) tuple/list/set/dict of literals, or a signed
    numeric literal. Calls/names/comprehensions are NOT literals, so
    `logger = getLogger()` / `MARKER_RE = re.compile(...)` are skipped."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_literal(k) and _is_literal(v)
                   for k, v in zip(node.keys, node.values))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_literal(node.operand)
    return False


def _value_repr(node) -> str:
    """One-line, length-capped source of an expression (value or annotation)."""
    s = re.sub(r"\s+", " ", ast.unparse(node)).strip()
    return s if len(s) <= MAX_VALUE_LEN else s[:MAX_VALUE_LEN] + "…"


def _is_enum_class(node) -> bool:
    for base in node.bases:
        n = _call_name(base)
        if n and (n.rsplit(".", 1)[-1] in _ENUM_BASES or n.endswith("Enum")):
            return True
    return False


_CODE_KINDS = {"function", "method", "class"}


def _drop_value_collisions(symbols: list[Symbol]) -> list[Symbol]:
    """A literal value-symbol (constant/enum_member/attribute) must never evict a
    same-named callable/class: symbols are keyed (path, name) with INSERT OR IGNORE,
    so a constant/field named like a same-file function or property would silently
    drop the definition. Prefer the definition (also the final runtime binding)."""
    code_names = {s.name for s in symbols if s.kind in _CODE_KINDS}
    return [s for s in symbols
            if s.kind in _CODE_KINDS or s.name not in code_names]


class _Analyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[Symbol] = []
        self.edges: list[Edge] = []
        self.stack: list[str] = []
        self.scope: list[str] = ["module"]   # "module" | "class" | "function"
        self.class_enum: list[bool] = []      # is the enclosing class an Enum?

    def _enter(self, qn: str, node, scope_kind: str) -> None:
        self.stack.append(qn)
        self.scope.append(scope_kind)
        self.generic_visit(node)
        self.scope.pop()
        self.stack.pop()

    def _from(self) -> str:
        return self.stack[-1] if self.stack else "<module>"

    def visit_FunctionDef(self, node) -> None:
        qn = ".".join(self.stack + [node.name]) if self.stack else node.name
        kind = "method" if self.stack else "function"
        self.symbols.append(Symbol(qn, kind, node.lineno, _signature(node),
                                   node.end_lineno))
        self._enter(qn, node, "function")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node) -> None:
        qn = ".".join(self.stack + [node.name]) if self.stack else node.name
        self.symbols.append(Symbol(qn, "class", node.lineno, _signature(node),
                                   node.end_lineno))
        for base in node.bases:
            tn = _call_name(base)
            if tn:
                self.edges.append(Edge(qn, tn, "inherit", node.lineno))
        self.class_enum.append(_is_enum_class(node))
        self._enter(qn, node, "class")
        self.class_enum.pop()

    def visit_Call(self, node) -> None:
        tn = _call_name(node.func)
        if tn:
            fn = self._from()
            self.edges.append(Edge(fn, tn, "call", node.lineno))
            if "." in tn:
                self.edges.append(Edge(fn, tn.rsplit(".", 1)[-1], "call", node.lineno))
        self.generic_visit(node)

    def visit_Import(self, node) -> None:
        fn = self._from()
        for alias in node.names:
            self.edges.append(Edge(fn, alias.name, "import", node.lineno))

    def visit_ImportFrom(self, node) -> None:
        fn = self._from()
        mod = node.module or ""
        for alias in node.names:
            target = f"{mod}.{alias.name}" if mod else alias.name
            self.edges.append(Edge(fn, target, "import", node.lineno))

    def visit_Assign(self, node) -> None:
        # generic_visit FIRST so call edges in the RHS (e.g. X = compute()) survive.
        self.generic_visit(node)
        scope = self.scope[-1]
        if scope == "function":
            return                                  # locals are noise
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return                                  # skip tuple/chained targets
        if not _is_literal(node.value):             # only surface real literal values
            return                                  # (a base named *Enum can misfire)
        name = node.targets[0].id
        kind = ("enum_member" if (scope == "class" and self.class_enum
                                  and self.class_enum[-1]) else "constant")
        qn = ".".join(self.stack + [name]) if self.stack else name
        self.symbols.append(Symbol(qn, kind, node.lineno,
                                   f"{name} = {_value_repr(node.value)}",
                                   node.end_lineno))

    def visit_AnnAssign(self, node) -> None:
        self.generic_visit(node)
        scope = self.scope[-1]
        if scope == "function" or not isinstance(node.target, ast.Name):
            return
        name = node.target.id
        if scope == "class":                        # declared field: show its type
            sig = f"{name}: {_value_repr(node.annotation)}"
            if node.value is not None and _is_literal(node.value):
                sig += f" = {_value_repr(node.value)}"
            kind = "enum_member" if (self.class_enum and self.class_enum[-1]) else "attribute"
            self.symbols.append(Symbol(".".join(self.stack + [name]), kind,
                                       node.lineno, sig, node.end_lineno))
        elif node.value is not None and _is_literal(node.value):   # module constant
            self.symbols.append(Symbol(name, "constant", node.lineno,
                                       f"{name} = {_value_repr(node.value)}",
                                       node.end_lineno))


class PythonParser:
    extensions = (".py",)

    def parse(self, path: Path) -> ParseResult:
        src = path.read_text(encoding="utf-8", errors="replace")
        lc = src.count("\n") + 1
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            return ParseResult(symbols=[], edges=[], line_count=lc)
        az = _Analyzer()
        az.visit(tree)
        return ParseResult(symbols=_drop_value_collisions(az.symbols),
                           edges=az.edges, line_count=lc)


register(PythonParser())
