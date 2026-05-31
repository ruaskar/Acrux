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


_STR_NODES = ("string", "template_string")
# Subtrees to keep verbatim: a type annotation is type info, not a runtime value,
# so it can't carry a default credential — and in tree-sitter-typescript the
# `string` TYPE keyword is itself a node of type `string`, so descending into an
# annotation would clobber `: string` → `: <str>`. Pruning here also keeps literal
# types (`: "a" | "b"`), matching the Python parser keeping `Literal[...]`.
_SKIP_SUBTREES = ("type_annotation",)


def _collect_str_spans(node, spans: list[tuple[int, int]]) -> None:
    """(start_byte, end_byte) of every string / template-string DEFAULT-value node.
    Skips type_annotation subtrees (kept verbatim) and does NOT recurse into a
    string once found (a template's `${...}` is replaced whole)."""
    if node.type in _SKIP_SUBTREES:
        return
    if node.type in _STR_NODES:
        spans.append((node.start_byte, node.end_byte))
        return
    for c in node.children:
        _collect_str_spans(c, spans)


def _params(node) -> str:
    """Parameter list as text, with every string/template literal DEFAULT replaced
    by `<str>`. SECURITY: a parameter's string DEFAULT can hold a hardcoded
    credential, so — mirroring the Python parser's value-hiding — no string VALUE
    may appear in a signature. We hide string literals structurally (not by
    secret-detection), but keep type annotations verbatim (parity with the Python
    parser, which keeps `Literal[...]`). Param names, numeric / boolean / identifier
    defaults, and type annotations are all kept."""
    p = _field(node, "parameters")
    if p is None:
        return "()"
    spans: list[tuple[int, int]] = []
    _collect_str_spans(p, spans)
    if not spans:
        return _txt(p)
    src, base = p.text, p.start_byte
    out, cur = bytearray(), base
    for s, e in sorted(spans):
        out += src[cur - base:s - base]
        out += b"<str>"
        cur = e
    out += src[cur - base:]
    return out.decode("utf-8", errors="replace")


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
            params = _params(node)
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
            params = _params(node)
            qn = self._qual(name)
            self.symbols.append(Symbol(qn, "method", self._line(node),
                                       f"{name}{params}", self._end(node)))
            self.funcs.append(qn); self._children(node); self.funcs.pop(); descended = True

        elif t == "variable_declarator":
            val = _field(node, "value")
            if val is not None and val.type in (
                    "arrow_function", "function", "function_expression"):
                name = _field_text(node, "name") or "?"
                params = _params(val)
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
