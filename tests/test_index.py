from keymd.engine import config, db, index
import keymd.engine.parsers.python  # noqa: F401  (registers the parser)


def test_build_populates_tables_and_resolves_edges(env_proj):
    stats = index.build(verbose=False)
    assert stats["files"] >= 2
    con = db.connect(config.index_path())
    # symbols
    names = {r[0] for r in con.execute("SELECT name FROM symbols").fetchall()}
    assert {"parse_header", "Parser", "Parser.parse", "run"} <= names
    # an edge from pipeline → parser got resolved to a project path
    row = con.execute(
        "SELECT to_path FROM edges WHERE to_name='parse_header' "
        "AND kind='call' AND to_path IS NOT NULL LIMIT 1").fetchone()
    assert row is not None and row[0].endswith("parser.py")
    con.close()
