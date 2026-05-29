from keymd.engine import db


def test_connect_creates_schema(tmp_path):
    p = tmp_path / "index.db"
    con = db.connect(p, create=True)
    names = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()}
    assert {"files", "symbols", "edges", "keymds"} <= names
    # FTS5 must be available.
    con.execute("INSERT INTO keymd_fts(path, content) VALUES ('a','hello')")
    rows = con.execute(
        "SELECT path FROM keymd_fts WHERE keymd_fts MATCH 'hello'").fetchall()
    assert rows == [("a",)]
    con.close()


def test_symbols_has_signature_column(tmp_path):
    con = db.connect(tmp_path / "i.db", create=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(symbols)").fetchall()}
    assert "signature" in cols
    con.close()
