"""Phase-A: symbol line anchors, ranged reads, and the keymd_edit write tool."""
import pytest

from keymd.engine import config, index
from keymd.engine.keymd_render import render_keymd
from keymd.engine.parsers.python import PythonParser
from keymd.engine import db
from keymd.proxy import engine, tools
from keymd.proxy.adapters.base import ToolCall

SRC = (
    "def alpha(x):\n"        # L1
    "    return x + 1\n"     # L2
    "\n"                     # L3
    "\n"                     # L4
    "class Beta:\n"          # L5
    "    def go(self):\n"    # L6
    "        return alpha(2)\n"  # L7
)


@pytest.fixture
def tmp_proj(monkeypatch, tmp_path):
    (tmp_path / "m.py").write_text(SRC, encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    index.build(verbose=False)
    return tmp_path


def _abs(root, name="m.py"):
    return engine.canon(str(root / name))


# --- end_line on symbols ----------------------------------------------------
def test_parser_captures_end_line(tmp_path):
    p = tmp_path / "m.py"
    p.write_text(SRC, encoding="utf-8")
    syms = {s.name: s for s in PythonParser().parse(p).symbols}
    assert syms["alpha"].end_line == 2
    assert syms["Beta"].end_line == 7
    assert syms["Beta.go"].end_line == 7


# --- anchors in the summary -------------------------------------------------
def test_render_emits_line_anchors(tmp_proj):
    con = db.connect(config.index_path())
    text = render_keymd(con, _abs(tmp_proj))
    con.close()
    assert "# L1-2" in text     # alpha spans L1-2
    assert "# L5-7" in text     # class Beta spans L5-7


# --- ranged reads -----------------------------------------------------------
def test_read_range_returns_only_those_lines(tmp_proj):
    out = engine.read_range(_abs(tmp_proj), 1, 2)
    assert "def alpha(x):" in out and "return x + 1" in out
    assert "class Beta" not in out


def test_read_symbol_returns_the_symbol(tmp_proj):
    out = engine.read_symbol(_abs(tmp_proj), "alpha")
    assert "def alpha(x):" in out and "return x + 1" in out
    assert "class Beta" not in out


def test_read_symbol_unknown_is_graceful(tmp_proj):
    assert "not found" in engine.read_symbol(_abs(tmp_proj), "nope")


def test_read_range_refuses_outside_root(tmp_proj, tmp_path):
    outside = str((tmp_path.parent / "elsewhere.txt").resolve())
    assert "refused" in engine.read_range(outside, 1, 5)


def test_read_range_truncates_with_notice(tmp_proj):
    big = tmp_proj / "big.txt"
    big.write_text("\n".join(f"line{i}" for i in range(1, 1001)) + "\n",
                   encoding="utf-8")
    out = engine.read_range(engine.canon(str(big)), 1, 1000)   # 1000 > 800 cap
    assert "truncated at 800 lines" in out      # never silently cut
    assert "line1\n" in out                     # head is present


# --- keymd_edit -------------------------------------------------------------
def test_edit_applies_and_reindexes(tmp_proj):
    ap = _abs(tmp_proj)
    res = engine.edit(ap, "return x + 1", "return x + 100")
    assert "re-indexed" in res
    assert "return x + 100" in (tmp_proj / "m.py").read_text(encoding="utf-8")
    # the fresh index reflects the edit (proves sync_one ran)
    assert "return x + 100" in engine.read_symbol(ap, "alpha")


def test_edit_refuses_non_unique(tmp_proj):
    # "return" appears twice (alpha + Beta.go) → must refuse, file untouched
    res = engine.edit(_abs(tmp_proj), "return", "yield")
    assert "appears 2 times" in res
    assert "yield" not in (tmp_proj / "m.py").read_text(encoding="utf-8")


def test_edit_refuses_outside_root(tmp_proj, tmp_path):
    outside = str((tmp_path.parent / "victim.txt").resolve())
    assert "refused" in engine.edit(outside, "a", "b")


def test_edit_refuses_empty_old(tmp_proj):
    res = engine.edit(_abs(tmp_proj), "", "x")
    assert "must not be empty" in res
    assert (tmp_proj / "m.py").read_text(encoding="utf-8") == SRC  # untouched


def test_read_range_past_eof_is_graceful(tmp_proj):
    out = engine.read_range(_abs(tmp_proj), 999, 1005)
    assert "past end of file" in out


# --- tools are wired --------------------------------------------------------
def test_new_tools_advertised_and_dispatched(tmp_proj):
    names = {d["name"] for d in tools.VIRTUAL_TOOL_DEFS}
    assert {"keymd_read_symbol", "keymd_read_range", "keymd_edit"} <= names
    out = tools.answer(ToolCall("1", "keymd_read_range",
                                {"path": _abs(tmp_proj), "start": 1, "end": 2}))
    assert "def alpha(x):" in out
