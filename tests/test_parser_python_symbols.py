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
    by_name = {s.name: s for s in r.symbols}

    # NUMERIC constant: value shown verbatim (a number can't carry a credential)
    assert by_name["MAX_DEPS"].kind == "constant"
    assert by_name["MAX_DEPS"].signature == "MAX_DEPS = 10"
    # collection containing STRINGS collapses to its type (security policy)
    assert by_name["READ_TOOLS"].kind == "constant"
    assert by_name["READ_TOOLS"].signature == "READ_TOOLS = <set>"

    # non-literal RHS (a call) is NOT surfaced
    assert "logger" not in by_name

    # a string value is rendered as its TYPE, never its content (no leak, no truncation)
    assert by_name["BLURB"].signature == "BLURB = <str>"

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
    assert by_name["C.LABEL"].signature == "LABEL = <str>"   # string value hidden


# Every vector an adversarial red-team confirmed leaking past the old regex
# redaction. Policy now: string/bytes VALUES are never emitted (shown as a type),
# so none of these can reach a summary regardless of name, shape, length, or nesting.
SECRETS_SRC = '''
API_KEY = "sk-ant-api03-aBcDeFgHiJkLmNoPqRsT"
DATABASE_URL = "postgresql://aotc:aotc2026@localhost:5432/aotc"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLE"
GH_PAT = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
DATA_BLOB = "''' + ("a" * 70) + '''"
CONN = "Password=P@ssw0rd123!;Server=x"
SLACK = "https://hooks.slack.com/services/T024BE7LH/B024BE7LH/abcd1234efghIJKL"
H = "Bearer aBcDeF1234567890GhIjKl"
PASSWORD = "hunter2"
CONFIG = {"password": "hunter2", "host": "db"}
CREDS = ["user", ["pw", "hunter2"]]
SECRET_KEY = b"my secret pass"

MAX_DEPS = 10
NUMS = (1, 2, 3)

class Cfg:
    token: str = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    kind: str = "host"

def connect(password="hunter2", auth="Bearer abc123xyz4567890", verbose=False):
    return 1
'''

# substrings that must NEVER appear in any emitted signature
_LEAK_NEEDLES = [
    "sk-ant-api03", "aotc2026", "wJalrXUtnFEMI", "ghp_AbCdEf",
    "a" * 30, "P@ssw0rd123", "abcd1234efghIJKL", "Bearer aBcDeF",
    "hunter2", "my secret pass", "abc123xyz4567890",
]


def test_no_string_value_can_leak(tmp_path):
    f = tmp_path / "cfg.py"
    f.write_text(SECRETS_SRC, encoding="utf-8")
    by = {s.name: s.signature for s in PythonParser().parse(f).symbols}
    blob = "\n".join(by.values())

    for needle in _LEAK_NEEDLES:
        assert needle not in blob, f"secret leaked: {needle!r}"

    # strings/bytes (and collections holding them) render as their TYPE
    assert by["API_KEY"] == "API_KEY = <str>"
    assert by["DATABASE_URL"] == "DATABASE_URL = <str>"
    assert by["DATA_BLOB"] == "DATA_BLOB = <str>"     # 70 chars — old truncation leaked this
    assert by["CONN"] == "CONN = <str>"
    assert by["SLACK"] == "SLACK = <str>"
    assert by["SECRET_KEY"] == "SECRET_KEY = <bytes>"
    assert by["CONFIG"] == "CONFIG = <dict>"          # secret under innocuous-named dict key
    assert by["CREDS"] == "CREDS = <list>"            # nested-list secret
    assert by["Cfg.token"] == "token: str = <str>"    # class attr default
    # function default-arg string values hidden
    assert by["connect"] == "def connect(password=<str>, auth=<str>, verbose=False)"

    # numbers / numeric collections / type annotations PRESERVED (#18's value-lookup win)
    assert by["MAX_DEPS"] == "MAX_DEPS = 10"
    assert by["NUMS"] == "NUMS = (1, 2, 3)"
    assert by["Cfg.kind"] == "kind: str = <str>"      # annotation kept, default hidden
