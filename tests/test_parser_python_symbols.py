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


VALUES_SRC = '''
import logging
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Literal

MAX_DEPS = 10
READ_TOOLS = {"Read", "cat"}
BLURB = "''' + ("x" * 200) + '''"
logger = logging.getLogger(__name__)


class Color(IntEnum):
    RED = 1
    GREEN = 2


@dataclass
class D:
    kind: Literal["a", "b"]
    path: str | None = None
    x: list = field(default_factory=list)


def f():
    LOCAL = 1
    return LOCAL


A, B = 1, 2
'''


def test_constants_enums_and_fields(tmp_path):
    f = tmp_path / "v.py"
    f.write_text(VALUES_SRC, encoding="utf-8")
    r = PythonParser().parse(f)
    from keymd.engine.parsers.python import MAX_VALUE_LEN
    by_name = {s.name: s for s in r.symbols}

    # module-level scalar + collection constants (value-bearing signature)
    assert by_name["MAX_DEPS"].kind == "constant"
    assert by_name["MAX_DEPS"].signature == "MAX_DEPS = 10"
    assert by_name["READ_TOOLS"].kind == "constant"
    assert by_name["READ_TOOLS"].signature == "READ_TOOLS = {'Read', 'cat'}"

    # non-literal RHS (a call) is NOT surfaced
    assert "logger" not in by_name

    # long values are truncated with an ellipsis
    assert by_name["BLURB"].signature.endswith("…")
    assert len(by_name["BLURB"].signature) <= len("BLURB = ") + MAX_VALUE_LEN + 1

    # enum members carry their value
    assert by_name["Color.RED"].kind == "enum_member"
    assert by_name["Color.RED"].signature == "RED = 1"
    assert by_name["Color.GREEN"].signature == "GREEN = 2"

    # dataclass annotated fields: type shown; literal default shown; factory default hidden
    assert by_name["D.kind"].kind == "attribute"
    assert by_name["D.kind"].signature == "kind: Literal['a', 'b']"
    assert by_name["D.path"].signature == "path: str | None = None"
    assert by_name["D.x"].signature == "x: list"

    # function-local assignment is noise — not a symbol
    assert "LOCAL" not in by_name
    assert "f.LOCAL" not in by_name

    # tuple-target assignment is skipped (single Name targets only)
    assert "A" not in by_name and "B" not in by_name


def test_value_symbol_never_evicts_callable(tmp_path):
    # A literal constant must not shadow a same-named function via the index's
    # (path, name) PRIMARY KEY + INSERT OR IGNORE — the def must survive.
    f = tmp_path / "c.py"
    f.write_text("TIMEOUT = 30\ndef TIMEOUT():\n    return 1\n", encoding="utf-8")
    r = PythonParser().parse(f)
    by = {(s.name, s.kind) for s in r.symbols}
    assert ("TIMEOUT", "function") in by
    assert ("TIMEOUT", "constant") not in by


def test_field_never_evicts_property(tmp_path):
    # A typed class field sharing a name with a property (Pydantic/descriptor
    # pattern) must not drop the property.
    f = tmp_path / "p.py"
    f.write_text("class C:\n    value: int = 0\n    @property\n"
                 "    def value(self):\n        return self._v\n", encoding="utf-8")
    r = PythonParser().parse(f)
    assert {s.kind for s in r.symbols if s.name == "C.value"} == {"method"}


def test_enum_misfire_does_not_leak_nonliteral(tmp_path):
    # A non-enum base merely *named* like an enum (endswith 'Enum') must not turn
    # arbitrary call-valued class assignments into surfaced "values".
    f = tmp_path / "e.py"
    f.write_text("class C(MyBaseEnum):\n    handler = make_handler()\n"
                 "    LABEL = 'x'\n", encoding="utf-8")
    r = PythonParser().parse(f)
    by_name = {s.name: s for s in r.symbols}
    assert "C.handler" not in by_name              # non-literal RHS not surfaced
    assert by_name["C.LABEL"].signature == "LABEL = 'x'"
