"""treesitter.py — JS/TS + Java/C/C++ parsers via tree-sitter (official grammar wheels).

Emits the same language-neutral ParseResult as the Python parser, behind the
same Parser interface. Uses `tree-sitter` (>=0.25) + `tree-sitter-javascript` /
`tree-sitter-typescript` / `tree-sitter-java` / `tree-sitter-c` / `tree-sitter-cpp`.
(The `tree-sitter-language-pack` convenience package ships a `builtins.Node` ABI
incompatible with tree_sitter 0.25's Query/Node, so we use the per-grammar wheels.)

Two walkers coexist: `_Walker` is the original field-shaped JS/TS walker (left
untouched); `_SpecWalker` is a generic, LangSpec-driven walker shared by Java/C/C++
(their node types differ, but name/sig/call/import extraction is uniform enough for
one spec-parametrized pass). Adding another C-family-ish language = one LangSpec.

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

import re
from dataclasses import dataclass
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


# --- C-family + Java: declarative spec-driven walker -------------------------
# The JS/TS `_Walker` above is field-shaped and JS-specific; rather than fork it
# per language (and risk the JS/TS tests), Java/C/C++ share ONE generic walker
# driven by per-language node-type sets. Name extraction is the only procedural
# bit: Java/JS expose a `name` field; C/C++ bury the name at the end of a
# `declarator` chain — `_name()` handles both.

@dataclass(frozen=True)
class LangSpec:
    funcs: frozenset       # function/method DEFINITION nodes (have a body) → symbol + call scope
    decls: frozenset       # function DECLARATION-only nodes (C++ prototypes/fields) → symbol
    classes: frozenset     # class/struct nodes → qualified-name scope + class symbol
    calls: frozenset       # call-expression nodes → call edge
    creations: frozenset   # object-creation nodes (Java `new T()`) → call edge to T
    imports: frozenset     # include/import nodes → import edge
    strs: frozenset        # string-literal node types to hide (security) in signatures


_JAVA_SPEC = LangSpec(
    funcs=frozenset({"method_declaration", "constructor_declaration"}),
    decls=frozenset(),
    classes=frozenset({"class_declaration", "interface_declaration",
                       "enum_declaration", "record_declaration"}),
    calls=frozenset({"method_invocation"}),
    creations=frozenset({"object_creation_expression"}),
    imports=frozenset({"import_declaration"}),
    strs=frozenset({"string_literal", "character_literal"}),
)
_C_SPEC = LangSpec(
    funcs=frozenset({"function_definition"}),
    decls=frozenset(),
    classes=frozenset(),
    calls=frozenset({"call_expression"}),
    creations=frozenset(),
    imports=frozenset({"preproc_include"}),
    strs=frozenset({"string_literal", "char_literal", "concatenated_string"}),
)
_CPP_SPEC = LangSpec(
    funcs=frozenset({"function_definition"}),
    decls=frozenset({"field_declaration", "declaration"}),
    classes=frozenset({"class_specifier", "struct_specifier"}),
    calls=frozenset({"call_expression"}),
    creations=frozenset(),
    imports=frozenset({"preproc_include"}),
    strs=frozenset({"string_literal", "raw_string_literal", "char_literal",
                    "concatenated_string"}),
)

_NAME_DESCENT = 16  # max declarator-tree depth when locating a C/C++ function name

# A real C/C++ function name is one of these node types at the end of the
# declarator. Anything else (notably `parenthesized_declarator`, which is how
# tree-sitter shapes a function-POINTER variable `int (*fp)(int)`) is NOT a
# function name — accepting it would emit variables as bogus symbols.
_FUNC_NAME_NODES = frozenset({
    "identifier", "field_identifier", "qualified_identifier",
    "destructor_name", "operator_name",
})


def _leaf(s: str) -> str:
    return s.split("::")[-1].split(".")[-1]


class _SpecWalker:
    """Generic recursive-descent walker for Java/C/C++, driven by a LangSpec.
    Tracks class scope for qualified names and attributes calls to the enclosing
    function. Emits the same Symbol/Edge shapes as the Python and JS/TS parsers."""

    def __init__(self, spec: LangSpec) -> None:
        self.spec = spec
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

    def _name(self, node) -> str | None:
        nm = node.child_by_field_name("name")           # Java/JS-style direct name
        if nm is not None:
            return _txt(nm)
        # C/C++: the name sits at the end of a declarator chain whose shape varies
        # by return type — `pointer_declarator` exposes its inner via the
        # `declarator` field, but `reference_declarator` (T&/T&&, e.g. operator=,
        # accessors, fluent setters) does NOT, so a field-only walk silently drops
        # every reference-returning function. Bounded pre-order DFS for the FIRST
        # `function_declarator` handles every shape; scoped to the declarator
        # subtree (a sibling of `body`), so a callback-param's nested
        # function_declarator can't win and the body is never entered.
        fd = self._find_func_declarator(node.child_by_field_name("declarator"))
        if fd is not None:
            inner = fd.child_by_field_name("declarator")
            # Only an identifier-like inner is a real function name; a
            # `parenthesized_declarator` is a function-POINTER variable, not a
            # function — reject it so variables aren't emitted as symbols.
            if inner is not None and inner.type in _FUNC_NAME_NODES:
                return _txt(inner)
        return None

    def _find_func_declarator(self, node, depth: int = 0):
        if node is None or depth > _NAME_DESCENT:
            return None
        if node.type == "function_declarator":
            return node
        for c in node.children:
            r = self._find_func_declarator(c, depth + 1)
            if r is not None:
                return r
        return None

    def _sig(self, node) -> str:
        body = node.child_by_field_name("body")
        end = body.start_byte if body is not None else node.end_byte
        raw, base = node.text, node.start_byte
        # hide string-literal VALUES within the signature region (security parity)
        spans: list[tuple[int, int]] = []

        def collect(n):
            if n.start_byte >= end:
                return
            if n.type in self.spec.strs:
                spans.append((n.start_byte, n.end_byte))
                return
            for c in n.children:
                collect(c)

        collect(node)
        if spans:
            out, cur = bytearray(), base
            for s, e in sorted(spans):
                if s >= end:
                    break
                out += raw[cur - base:s - base]
                out += b"<str>"
                cur = e
            out += raw[cur - base:end - base]
            seg = bytes(out)
        else:
            seg = raw[:end - base]
        s = seg.decode("utf-8", errors="replace")
        s = re.sub(r"\s+", " ", s).strip().rstrip("{").rstrip().rstrip(";").strip()
        return s

    def _call_name(self, node) -> str | None:
        fn = node.child_by_field_name("function")       # C/C++ call_expression
        if fn is not None:
            if fn.type == "field_expression":
                p = fn.child_by_field_name("field")
                return _txt(p) if p is not None else None
            if fn.type in ("scoped_identifier", "qualified_identifier"):
                return _leaf(_txt(fn))
            return _txt(fn)
        nm = node.child_by_field_name("name")            # Java method_invocation
        return _txt(nm) if nm is not None else None

    def _import_target(self, node) -> str | None:
        for c in node.children:                          # C/C++ preproc_include
            if c.type in ("system_lib_string", "string_literal"):
                return _txt(c).strip('<>"')
        for c in node.named_children:                    # Java import_declaration
            if c.type in ("scoped_identifier", "identifier"):
                base = _txt(c)
                # `import a.b.*;` parses as scoped_identifier(a.b) + asterisk —
                # preserve the wildcard so it's distinguishable from a type import.
                if any(k.type == "asterisk" for k in node.children):
                    return base + ".*"
                return base
        return None

    def visit(self, node) -> None:
        t = node.type
        spec = self.spec
        descended = False

        if t in spec.classes:
            name = self._name(node)
            if name:
                self.symbols.append(Symbol(self._qual(name), "class",
                                           self._line(node), self._sig(node), self._end(node)))
                self.classes.append(name); self._children(node); self.classes.pop()
                descended = True
        elif t in spec.funcs:
            name = self._name(node)
            if name:
                qn = self._qual(name)
                kind = "method" if (self.classes or "::" in name) else "function"
                self.symbols.append(Symbol(qn, kind, self._line(node),
                                           self._sig(node), self._end(node)))
                self.funcs.append(qn); self._children(node); self.funcs.pop()
                descended = True
        elif t in spec.decls:
            name = self._name(node)
            if name:                                     # function_declarator present → a method/fn decl
                qn = self._qual(name)
                kind = "method" if (self.classes or "::" in name) else "function"
                self.symbols.append(Symbol(qn, kind, self._line(node),
                                           self._sig(node), self._end(node)))
        elif t in spec.calls:
            nm = self._call_name(node)
            if nm:
                self.edges.append(Edge(self._from(), nm, "call", self._line(node)))
        elif t in spec.creations:
            ty = node.child_by_field_name("type")
            if ty is not None:
                self.edges.append(Edge(self._from(), _leaf(_txt(ty)), "call", self._line(node)))
        elif t in spec.imports:
            tgt = self._import_target(node)
            if tgt:
                self.edges.append(Edge("<module>", tgt, "import", self._line(node)))

        if not descended:
            self._children(node)

    def _children(self, node) -> None:
        for c in node.children:
            self.visit(c)


class _TreeSitterParser:
    def __init__(self, language, extensions: tuple[str, ...], walker=None) -> None:
        from tree_sitter import Parser
        self._parser = Parser(language)
        self.extensions = extensions
        self._walker = walker or (lambda: _Walker())

    def parse(self, path: Path) -> ParseResult:
        data = path.read_bytes()
        lc = data.count(b"\n") + 1
        tree = self._parser.parse(data)
        w = self._walker()
        w.visit(tree.root_node)
        return ParseResult(symbols=w.symbols, edges=w.edges, line_count=lc)


def _register() -> None:
    try:
        from tree_sitter import Language
    except ImportError:
        return  # core tree_sitter absent — `lang` extra not installed, engine stays Python-only
    # JS/TS (optional, independent of the C-family below)
    try:
        import tree_sitter_javascript as tsjs
        import tree_sitter_typescript as tsts
        register(_TreeSitterParser(Language(tsjs.language()),
                                   (".js", ".jsx", ".mjs", ".cjs")))
        register(_TreeSitterParser(Language(tsts.language_typescript()), (".ts",)))
        register(_TreeSitterParser(Language(tsts.language_tsx()), (".tsx",)))
    except ImportError:
        pass
    # C-family + Java — each grammar independently optional. `.h` → C++ grammar
    # (a near-superset that parses C headers); C registered before C++ so C++ wins `.h`.
    import importlib
    _CLANG = [
        ("tree_sitter_java", (".java",), _JAVA_SPEC),
        ("tree_sitter_c", (".c",), _C_SPEC),
        ("tree_sitter_cpp",
         (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"), _CPP_SPEC),
    ]
    for mod_name, exts, spec in _CLANG:
        try:
            mod = importlib.import_module(mod_name)
            register(_TreeSitterParser(Language(mod.language()), exts,
                                       lambda spec=spec: _SpecWalker(spec)))
        except Exception:
            continue


_register()
