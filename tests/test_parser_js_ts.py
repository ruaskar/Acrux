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
