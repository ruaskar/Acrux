"""treesitter.py — JS/TS parsers via tree-sitter (official grammar wheels).

Emits the same language-neutral ParseResult as the Python parser, behind the
same Parser interface. Uses `tree-sitter` (>=0.25) + `tree-sitter-javascript` /
`tree-sitter-typescript`. (The `tree-sitter-language-pack` convenience package
ships a `builtins.Node` ABI incompatible with tree_sitter 0.25's Query/Node, so
we use the official per-grammar wheels.)

SCOPE / HONESTY: symbols, signatures, import deps, and resolved callees are
accurate for JS/TS. The import-gated CALLER heuristic in graph.callers_for_symbol
is Python-module-tuned (dotted import patterns + STDLIB_STEMS); JS/TS use
path-style module specifiers, so `called_by`/`impact` for JS/TS rely on the
language-agnostic unique-defender edge resolution and are best-effort.
Full JS/TS module resolution is a future refinement.

If the tree-sitter wheels are not installed, this module self-disables on import
(register() is simply never called) and the engine remains Python-only.
"""
from __future__ import annotations

from pathlib import Path

from keymd.engine.parsers.base import Edge, ParseResult, Symbol, register


def _txt(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _field(node, name: str):
    return node.child_by_field_name(name)


def _field_text(node, name: str) -> str | None:
    c = _field(node, name)
    return _txt(c) if c is not None else None


class _Walker:
    """Recursive descent tracking class + function scope to build qualified
    names and attribute calls to their enclosing function/method."""

    def __init__(self) -> None:
        self.symbols: list[Symbol] = []
        self.edges: list[Edge] = []
        self.classes: list[str] = []
        self.funcs: list[str] = []

    def _from(self) -> str:
        return self.funcs[-1] if self.funcs else "<module>"

    def _qual(self, name: str) -> str:
        return ".".join(self.classes + [name]) if self.classes else name

    def _line(self, node) -> int:
        return node.start_point[0] + 1

    def _end(self, node) -> int:
        return node.end_point[0] + 1

    def visit(self, node) -> None:
        t = node.type
        descended = False

        if t in ("function_declaration", "generator_function_declaration"):
            name = _field_text(node, "name") or "?"
            params = _field_text(node, "parameters") or "()"
            qn = self._qual(name)
            kind = "method" if self.classes else "function"
            self.symbols.append(Symbol(qn, kind, self._line(node),
                                       f"function {name}{params}", self._end(node)))
            self.funcs.append(qn); self._children(node); self.funcs.pop(); descended = True

        elif t == "class_declaration":
            name = _field_text(node, "name") or "?"
            self.symbols.append(Symbol(self._qual(name), "class", self._line(node),
                                       f"class {name}", self._end(node)))
            self.classes.append(name); self._children(node); self.classes.pop(); descended = True

        elif t == "method_definition":
            name = _field_text(node, "name") or "?"
            params = _field_text(node, "parameters") or "()"
            qn = self._qual(name)
            self.symbols.append(Symbol(qn, "method", self._line(node),
                                       f"{name}{params}", self._end(node)))
            self.funcs.append(qn); self._children(node); self.funcs.pop(); descended = True

        elif t == "variable_declarator":
            val = _field(node, "value")
            if val is not None and val.type in (
                    "arrow_function", "function", "function_expression"):
                name = _field_text(node, "name") or "?"
                params = _field_text(val, "parameters") or "()"
                qn = self._qual(name)
                kind = "method" if self.classes else "function"
                self.symbols.append(Symbol(qn, kind, self._line(node),
                                           f"{name}{params}", self._end(node)))
                self.funcs.append(qn); self._children(node); self.funcs.pop(); descended = True

        elif t == "call_expression":
            fn = _field(node, "function")
            if fn is not None:
                if fn.type == "identifier":
                    self.edges.append(Edge(self._from(), _txt(fn), "call", self._line(node)))
                elif fn.type == "member_expression":
                    self.edges.append(Edge(self._from(), _txt(fn), "call", self._line(node)))
                    prop = _field(fn, "property")
                    if prop is not None:
                        self.edges.append(Edge(self._from(), _txt(prop), "call", self._line(node)))

        elif t == "import_statement":
            src = _field(node, "source")
            if src is not None:
                self.edges.append(Edge("<module>", _txt(src).strip("'\"\\`"),
                                       "import", self._line(node)))

        if not descended:
            self._children(node)

    def _children(self, node) -> None:
        for c in node.children:
            self.visit(c)


class _TreeSitterParser:
    def __init__(self, language, extensions: tuple[str, ...]) -> None:
        from tree_sitter import Parser
        self._parser = Parser(language)
        self.extensions = extensions

    def parse(self, path: Path) -> ParseResult:
        data = path.read_bytes()
        lc = data.count(b"\n") + 1
        tree = self._parser.parse(data)
        w = _Walker()
        w.visit(tree.root_node)
        return ParseResult(symbols=w.symbols, edges=w.edges, line_count=lc)


def _register() -> None:
    try:
        import tree_sitter_javascript as tsjs
        import tree_sitter_typescript as tsts
        from tree_sitter import Language
    except ImportError:
        return  # `lang` extra not installed — engine stays Python-only
    register(_TreeSitterParser(Language(tsjs.language()),
                               (".js", ".jsx", ".mjs", ".cjs")))
    register(_TreeSitterParser(Language(tsts.language_typescript()), (".ts",)))
    register(_TreeSitterParser(Language(tsts.language_tsx()), (".tsx",)))


_register()
