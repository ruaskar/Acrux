from keymd.engine.parsers.python import PythonParser

SRC = '''
from pkg.parser import Parser, parse_header
import os


def run(stream):
    p = Parser()
    parse_header(b"x")
    return p.parse(stream)
'''


def test_edges(tmp_path):
    f = tmp_path / "pipeline.py"
    f.write_text(SRC, encoding="utf-8")
    r = PythonParser().parse(f)
    triples = {(e.from_name, e.to_name, e.kind) for e in r.edges}
    # imports
    assert ("<module>", "pkg.parser.Parser", "import") in triples
    assert ("<module>", "pkg.parser.parse_header", "import") in triples
    assert ("<module>", "os", "import") in triples
    # calls (full + leaf for dotted)
    assert ("run", "parse_header", "call") in triples
    assert ("run", "Parser", "call") in triples
    assert ("run", "p.parse", "call") in triples
    assert ("run", "parse", "call") in triples  # leaf of p.parse
