"""python.py — Python source parser using the stdlib `ast` module.

Emits language-neutral ParseResult (symbols + edges). Chosen over tree-sitter
for Python because `ast` is zero-dependency, exact, and battle-tested; JS/TS
parsers (Phase 1b) use tree-sitter behind the same Parser interface.
"""
from __future__ import annotations

import ast
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


class _Analyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[Symbol] = []
        self.edges: list[Edge] = []
        self.stack: list[str] = []

    def _enter(self, qn: str, node) -> None:
        self.stack.append(qn)
        self.generic_visit(node)
        self.stack.pop()

    def _from(self) -> str:
        return self.stack[-1] if self.stack else "<module>"

    def visit_FunctionDef(self, node) -> None:
        qn = ".".join(self.stack + [node.name]) if self.stack else node.name
        kind = "method" if self.stack else "function"
        self.symbols.append(Symbol(qn, kind, node.lineno, _signature(node),
                                   node.end_lineno))
        self._enter(qn, node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node) -> None:
        qn = ".".join(self.stack + [node.name]) if self.stack else node.name
        self.symbols.append(Symbol(qn, "class", node.lineno, _signature(node),
                                   node.end_lineno))
        for base in node.bases:
            tn = _call_name(base)
            if tn:
                self.edges.append(Edge(qn, tn, "inherit", node.lineno))
        self._enter(qn, node)

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
        return ParseResult(symbols=az.symbols, edges=az.edges, line_count=lc)


register(PythonParser())
