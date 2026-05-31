import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_javascript")
pytest.importorskip("tree_sitter_typescript")

from pathlib import Path  # noqa: E402

from keymd.engine.parsers.base import get_parser_for  # noqa: E402
import keymd.engine.parsers.treesitter  # noqa: F401,E402

JS = '''import {foo} from "./mod";
function run(a, b) { return foo(a); }
const arrow = (x) => bar(x);
class Parser { parse(s) { return foo(s); } }
'''

TS = '''export function add(a: number, b: number): number { return a + b; }
class Svc { run(x: string): void { helper(x); } }
'''


def test_js_symbols_signatures_edges(tmp_path):
    f = tmp_path / "m.js"
    f.write_text(JS, encoding="utf-8")
    parser = get_parser_for(f)
    assert parser is not None
    r = parser.parse(f)
    by = {s.name: s for s in r.symbols}
    assert by["run"].kind == "function" and "(a, b)" in by["run"].signature
    assert by["arrow"].kind == "function"
    assert by["Parser"].kind == "class"
    assert by["Parser.parse"].kind == "method"
    triples = {(e.from_name, e.to_name, e.kind) for e in r.edges}
    assert ("<module>", "./mod", "import") in triples
    assert ("run", "foo", "call") in triples
    assert ("arrow", "bar", "call") in triples
    assert ("Parser.parse", "foo", "call") in triples


def test_ts_signatures_include_annotations(tmp_path):
    f = tmp_path / "m.ts"
    f.write_text(TS, encoding="utf-8")
    r = get_parser_for(f).parse(f)
    by = {s.name: s for s in r.symbols}
    assert "a: number" in by["add"].signature
    assert by["Svc.run"].kind == "method"
    triples = {(e.from_name, e.to_name, e.kind) for e in r.edges}
    assert ("Svc.run", "helper", "call") in triples


def test_extensions_route():
    assert get_parser_for(Path("a.ts")) is not None
    assert get_parser_for(Path("a.tsx")) is not None
    assert get_parser_for(Path("a.jsx")) is not None
    assert get_parser_for(Path("a.mjs")) is not None


# A string DEFAULT value in a JS/TS parameter must render as <str>, never the literal
# (a hardcoded credential in a default arg would otherwise reach the summary). Param
# NAMES and non-string defaults / type annotations are kept.
DEFAULTS = (
    'export function connect(url = "postgres://admin:p@db/x", retries = 3) {}\n'
    'const auth = (apiKey = "sk-secret-value", timeout = 30) => apiKey;\n'
    'class C { send(token = "ghp_xxx", n = 1) {} }\n'
)

TS_DEFAULTS = (
    'export function conn(url: string = "postgres://u:p@h/d", n: number = 5): void {}\n'
)


def test_js_string_defaults_are_hidden(tmp_path):
    f = tmp_path / "d.js"
    f.write_text(DEFAULTS, encoding="utf-8")
    by = {s.name: s for s in get_parser_for(f).parse(f).symbols}
    # secrets gone, param names + numeric defaults kept
    for nm in ("connect", "auth", "C.send"):
        sig = by[nm].signature
        assert '"' not in sig and "'" not in sig, f"{nm} kept a string literal: {sig}"
    assert "url" in by["connect"].signature and "retries = 3" in by["connect"].signature
    assert "<str>" in by["connect"].signature
    assert "apiKey" in by["auth"].signature and "timeout = 30" in by["auth"].signature
    assert "token" in by["C.send"].signature and "n = 1" in by["C.send"].signature


def test_ts_string_default_hidden_annotation_kept(tmp_path):
    f = tmp_path / "d.ts"
    f.write_text(TS_DEFAULTS, encoding="utf-8")
    sig = {s.name: s for s in get_parser_for(f).parse(f).symbols}["conn"].signature
    assert "postgres://" not in sig and '"' not in sig
    assert "url: string" in sig and "n: number = 5" in sig   # annotations survive
    assert "<str>" in sig
