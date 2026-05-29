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
