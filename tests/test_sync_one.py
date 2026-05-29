from pathlib import Path

from keymd.engine import config, db, index, refresh, sync_one
import keymd.engine.parsers.python  # noqa: F401


def test_sync_one_reindexes_and_refreshes(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    refresh.refresh_one(parser_py)  # ensure a sidecar exists to keep current
    key = Path(parser_py[:-3] + ".key.md")
    # append a new top-level function, then sync
    src = Path(parser_py).read_text(encoding="utf-8")
    Path(parser_py).write_text(src + "\n\ndef brand_new():\n    return 1\n",
                               encoding="utf-8")
    try:
        sync_one.sync_one(parser_py)
        con = db.connect(config.index_path())
        names = {r[0] for r in con.execute(
            "SELECT name FROM symbols WHERE path=?", (parser_py,)).fetchall()}
        assert "brand_new" in names
        con.close()
        assert "brand_new" in key.read_text(encoding="utf-8")
    finally:
        Path(parser_py).write_text(src, encoding="utf-8")  # restore fixture
        if key.exists():
            key.unlink()


def test_sync_one_clears_stale_incoming_pointer_on_rename(tmp_path, monkeypatch):
    # Renaming a symbol must not leave another file's resolved call edge pointing
    # at this file for the old name (the original sync_one's "Step 1" invalidation).
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / ".keymd" / "index.db"))
    from keymd.engine import config as c
    c.project_pkg_prefixes.cache_clear()
    c._git_toplevel.cache_clear()

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    a = pkg / "a.py"
    b = pkg / "b.py"
    a.write_text("def foo():\n    return 1\n", encoding="utf-8")
    b.write_text("from pkg.a import foo\n\n\ndef use():\n    return foo()\n",
                 encoding="utf-8")
    index.build(verbose=False)
    sp_a = config.canonical(str(a))
    sp_b = config.canonical(str(b))

    con = db.connect(config.index_path())
    row = con.execute("SELECT to_path FROM edges WHERE from_path=? AND to_name='foo' "
                      "AND kind='call'", (sp_b,)).fetchone()
    con.close()
    assert row is not None and row[0] == sp_a    # b.foo() resolved into a.py

    a.write_text("def bar():\n    return 1\n", encoding="utf-8")   # rename foo -> bar
    sync_one.sync_one(str(a))

    con = db.connect(config.index_path())
    row = con.execute("SELECT to_path FROM edges WHERE from_path=? AND to_name='foo' "
                      "AND kind='call'", (sp_b,)).fetchone()
    con.close()
    c.project_pkg_prefixes.cache_clear()
    c._git_toplevel.cache_clear()
    # the now-gone 'foo' must NOT still resolve to a.py (no dangling pointer)
    assert row is None or row[0] != sp_a
