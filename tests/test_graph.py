from keymd.engine import config, db, graph, index
import keymd.engine.parsers.python  # noqa: F401


def test_callers_for_symbol_finds_pipeline(env_proj):
    index.build(verbose=False)
    con = db.connect(config.index_path())
    cur = con.cursor()
    parser_path = next(
        r[0] for r in cur.execute("SELECT path FROM files").fetchall()
        if r[0].endswith("parser.py"))
    callers = graph.callers_for_symbol(cur, "parse_header", parser_path, "parser")
    assert any(c.endswith("pipeline.py") for c in callers)
    con.close()


def test_stdlib_stems_present():
    assert "os" in graph.STDLIB_STEMS and "re" in graph.STDLIB_STEMS
