from pathlib import Path

from keymd.engine.parsers.python import PythonParser

SRC = '''
def parse_header(buf: bytes) -> dict:
    return {}


class Parser:
    def parse(self, stream) -> list:
        return []
'''


def test_symbols_and_signatures(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(SRC, encoding="utf-8")
    r = PythonParser().parse(f)
    by_name = {s.name: s for s in r.symbols}
    assert by_name["parse_header"].kind == "function"
    assert by_name["parse_header"].signature == "def parse_header(buf: bytes) -> dict"
    assert by_name["Parser"].kind == "class"
    assert by_name["Parser.parse"].kind == "method"
    assert by_name["Parser.parse"].signature == "def parse(self, stream) -> list"
    assert r.line_count == SRC.count("\n") + 1
