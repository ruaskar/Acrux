from keymd.engine import config, db, index, keymd_render
import keymd.engine.parsers.python  # noqa: F401


def test_render_contains_api_and_callers(env_proj):
    index.build(verbose=False)
    con = db.connect(config.index_path())
    parser_path = next(
        r[0] for r in con.execute("SELECT path FROM files").fetchall()
        if r[0].endswith("parser.py"))
    text = keymd_render.render_keymd(con, parser_path)
    assert text.startswith("# ")
    assert "[python ·" in text
    assert "def parse_header(buf: bytes) -> dict" in text
    assert "called_by:" in text
    assert "pipeline.py" in text  # pipeline calls parse_header
    assert text.rstrip().splitlines()[-1].startswith("refreshed:")
    con.close()


VALS_SRC = (
    "from enum import IntEnum\n"
    "from dataclasses import dataclass\n"
    "from typing import Literal\n"
    "\n"
    "MAX_DEPS = 10\n"
    "\n"
    "class Color(IntEnum):\n"
    "    RED = 1\n"
    "    GREEN = 2\n"
    "\n"
    "@dataclass\n"
    "class D:\n"
    "    kind: Literal['a', 'b']\n"
    "    path: str | None = None\n"
)


def test_render_surfaces_constants_enum_and_fields(monkeypatch, tmp_path):
    """End-to-end: a module's constant, enum members, and dataclass field VALUES
    appear in the rendered .key.md, so definitional questions need no full read."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "vals.py").write_text(VALS_SRC, encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(proj))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()

    index.build(verbose=False)
    con = db.connect(config.index_path())
    path = next(r[0] for r in con.execute("SELECT path FROM files").fetchall()
                if r[0].endswith("vals.py"))
    text = keymd_render.render_keymd(con, path)
    con.close()

    assert "MAX_DEPS = 10" in text
    assert "RED = 1" in text and "GREEN = 2" in text
    # string contents inside a Literal are hidden (a Literal can embed a secret);
    # the type shape is kept, the values are not.
    assert "kind: Literal[<str>, <str>]" in text
    assert "path: str | None = None" in text


def test_constant_not_falsely_attributed_callers(monkeypatch, tmp_path):
    """A module constant must not appear in called_by: callers_for_symbol matches
    by leaf name + import gate, which would otherwise credit a data value with the
    callers of an unrelated same-named function in an importing file."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("parse = 1\n\ndef realfn():\n    return parse\n",
                               encoding="utf-8")
    (proj / "b.py").write_text(
        "from a import parse, realfn\n\ndef go():\n    return parse() + realfn()\n",
        encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(proj))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()

    index.build(verbose=False)
    con = db.connect(config.index_path())
    path = next(r[0] for r in con.execute("SELECT path FROM files").fetchall()
                if r[0].endswith("a.py"))
    text = keymd_render.render_keymd(con, path)
    con.close()

    called_by = text.split("called_by:", 1)[1]
    assert "parse" not in called_by      # the constant has no callers
    assert "realfn" in called_by         # the function still does


def test_render_idempotent_modulo_timestamp(env_proj):
    index.build(verbose=False)
    con = db.connect(config.index_path())
    parser_path = next(
        r[0] for r in con.execute("SELECT path FROM files").fetchall()
        if r[0].endswith("parser.py"))
    a = keymd_render.strip_timestamp(keymd_render.render_keymd(con, parser_path))
    b = keymd_render.strip_timestamp(keymd_render.render_keymd(con, parser_path))
    assert a == b
    con.close()
