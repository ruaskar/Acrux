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


def test_search_works_on_plain_build(env_proj):
    # A: FTS is populated from rendered summaries on every build — NO sidecar /
    # refresh dance needed (the old behavior required writing a .key.md first).
    index.build(verbose=False)
    hits = query.search("parse_header", limit=5)
    assert hits, "search found nothing on a plain build (FTS-over-summaries regressed)"
    # results point at the SOURCE file (you search to find code, not a sidecar)
    assert any(h["path"].endswith("parser.py") for h in hits)


def test_search_result_is_callgraph_enriched(env_proj):
    # B: each hit carries its structural context — the matched symbol and how many
    # files call into the hit file (centrality), so results are navigable + rankable.
    index.build(verbose=False)
    hits = query.search("parse_header", limit=5)
    top = next(h for h in hits if h["path"].endswith("parser.py"))
    assert "snippet" in top
    assert top.get("symbol")                      # the matched symbol name
    assert isinstance(top.get("called_by"), int)  # caller count (graph centrality)


def test_search_ranks_by_centrality(env_proj):
    # B: a hit in a file many things depend on outranks a hit in a leaf file.
    # parser.py is called by pipeline.py (>=1 caller); assert ordering is by
    # called_by desc so the more central hit comes first when terms tie.
    index.build(verbose=False)
    hits = query.search("parse", limit=10)
    cbs = [h["called_by"] for h in hits]
    assert cbs == sorted(cbs, reverse=True), "results not ranked by call-graph centrality"
