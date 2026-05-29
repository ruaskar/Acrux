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
