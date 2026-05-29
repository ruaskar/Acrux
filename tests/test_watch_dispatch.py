from pathlib import Path

from keymd.engine import config, db, index, query
from keymd.watcher import dispatch
import keymd.engine.parsers.python  # noqa: F401


def test_on_change_source_syncs(env_proj):
    index.build(verbose=False)
    pkg = Path(env_proj) / "pkg"
    parser_py = pkg / "parser.py"
    src = parser_py.read_text(encoding="utf-8")
    parser_py.write_text(src + "\n\ndef watched():\n    return 0\n", encoding="utf-8")
    try:
        dispatch.on_change(str(parser_py))
        con = db.connect(config.index_path())
        names = {r[0] for r in con.execute(
            "SELECT name FROM symbols WHERE path=?",
            (__import__("os").path.realpath(str(parser_py)),)).fetchall()}
        con.close()
        assert "watched" in names
    finally:
        parser_py.write_text(src, encoding="utf-8")
        (pkg / "parser.key.md").unlink(missing_ok=True)


def test_on_change_keymd_reindexes_fts(env_proj):
    index.build(verbose=False)
    pkg = Path(env_proj) / "pkg"
    key = pkg / "parser.key.md"
    key.write_text("# parser\napi:\n  zzunique_token\n", encoding="utf-8")
    try:
        dispatch.on_change(str(key))
        assert any("parser.key.md" in p for p, _ in query.search("zzunique_token"))
    finally:
        key.unlink(missing_ok=True)
