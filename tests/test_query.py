from pathlib import Path

from keymd.engine import index, query
import keymd.engine.parsers.python  # noqa: F401


def test_impact_lists_pipeline(env_proj):
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    res = query.impact(parser_py)
    callers = {c for sym in res["per_symbol"].values() for c in sym}
    assert any(c.endswith("pipeline.py") for c in callers)
    assert res["unique_files"] >= 1


def test_callees_resolved(env_proj):
    index.build(verbose=False)
    pipeline_py = str(Path(env_proj) / "pkg" / "pipeline.py")
    res = query.callees(pipeline_py)
    assert any(to_name == "parse_header" for to_name, _ in res)


def test_callers_leaf_fallback(env_proj):
    index.build(verbose=False)
    res = query.callers("Parser.parse")
    # No edge records the qualified 'Parser.parse'; the call is `p.parse`,
    # recorded under leaf 'parse'. exact must be empty, leaf must find run().
    assert res["exact"] == []
    assert any(name == "run" for _, name in res["leaf"])


def test_search_matches_after_keymd(env_proj):
    from keymd.engine import refresh
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    refresh.refresh_one(parser_py)
    index.build(verbose=False)  # re-index so the new .key.md enters FTS
    hits = query.search("parse_header", limit=5)
    try:
        assert any("parser.key.md" in path for path, _ in hits)
    finally:
        Path(parser_py[:-3] + ".key.md").unlink(missing_ok=True)
