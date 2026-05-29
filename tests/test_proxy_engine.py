from pathlib import Path

from keymd.engine import index
from keymd.proxy import engine
import keymd.engine.parsers.python  # noqa: F401


def test_facade_summary_and_indexed_large(env_proj):
    index.build(verbose=False)
    parser_py = engine.canon(str(Path(env_proj) / "pkg" / "parser.py"))
    s = engine.summary(parser_py)
    assert s and s.startswith("# ")
    assert engine.is_indexed_large(parser_py, threshold=0) is True
    assert engine.is_indexed_large(engine.canon(str(Path(env_proj) / "nope.py")),
                                   threshold=0) is False


def test_facade_full_reads_disk(env_proj):
    index.build(verbose=False)
    parser_py = engine.canon(str(Path(env_proj) / "pkg" / "parser.py"))
    assert "def parse_header" in engine.full(parser_py)


def test_full_refuses_outside_project_root(env_proj, tmp_path):
    index.build(verbose=False)
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-KEY-12345", encoding="utf-8")
    out = engine.full(engine.canon(str(secret)))
    assert "refused" in out
    assert "TOP-SECRET-KEY-12345" not in out  # contents never leak


def test_full_truncates_huge_file(env_proj, tmp_path, monkeypatch):
    # write a file inside the project root, larger than MAX_FULL_LINES
    monkeypatch.setattr(engine, "MAX_FULL_LINES", 5)
    big = Path(env_proj) / "pkg" / "_big_tmp.py"
    big.write_text("\n".join(f"x{i}=1" for i in range(50)), encoding="utf-8")
    try:
        out = engine.full(engine.canon(str(big)))
        assert "truncated" in out
        assert "x49=1" not in out  # tail dropped
    finally:
        big.unlink(missing_ok=True)


def test_search_survives_fts_syntax(env_proj):
    index.build(verbose=False)
    # these raise sqlite3.OperationalError if passed raw to FTS5 MATCH
    assert isinstance(engine.search("a AND b"), list)
    assert isinstance(engine.search("foo:bar"), list)
    assert isinstance(engine.search('"unterminated'), list)


def test_structure_queries_graceful_without_index(env_proj):
    # env_proj sets an index path but we deliberately do NOT build it
    assert engine.impact(engine.canon("x.py")) == {"error": "index not built — run `keymd build`"}
    assert engine.callees(engine.canon("x.py")) == []
    assert engine.search("anything") == []
    assert engine.summary(engine.canon("x.py")) is None
