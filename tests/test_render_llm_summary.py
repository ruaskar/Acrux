"""A cached LLM summary becomes the render `summary:` lead — which is what the
.key.md, the proxy gate, AND the graph side panel all consume via render_keymd."""
import keymd.engine.parsers.python  # noqa: F401
from keymd.engine import config, db, index, summary_store
from keymd.engine.keymd_render import render_keymd


def test_llm_summary_is_preferred_lead(tmp_path, monkeypatch):
    (tmp_path / "m.py").write_text(
        '"""Module docstring lead."""\ndef f():\n    return 1\n', encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear(); config._git_toplevel.cache_clear()
    index.build(verbose=False)
    con = db.connect(config.index_path())
    path = config.canonical(str(tmp_path / "m.py"))
    sha = con.execute("SELECT sha256 FROM files WHERE path=?", (path,)).fetchone()[0]

    # before: deterministic docstring lead
    assert "summary: Module docstring lead." in render_keymd(con, path)

    # after caching an LLM summary at the current sha: it WINS the lead
    summary_store.ensure_table(con)
    summary_store.put(con, path, sha, "LLM: parses and returns one.", "gpt-4o")
    out = render_keymd(con, path)
    assert "summary: LLM: parses and returns one." in out
    assert "Module docstring lead." not in out          # LLM summary replaces it

    # stale sha (file changed) -> LLM miss -> falls back to the docstring
    con.execute("UPDATE llm_summaries SET sha256='stale' WHERE path=?", (path,))
    con.commit()
    out2 = render_keymd(con, path)
    assert "summary: Module docstring lead." in out2
    con.close()


def test_render_tolerates_absent_llm_table(tmp_path, monkeypatch):
    """An index built before summarize ever ran has no llm_summaries table; render
    must not raise — it falls back to the docstring lead."""
    (tmp_path / "n.py").write_text(
        '"""Doc here."""\ndef g():\n    return 2\n', encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear(); config._git_toplevel.cache_clear()
    index.build(verbose=False)
    con = db.connect(config.index_path())
    path = config.canonical(str(tmp_path / "n.py"))
    con.execute("DROP TABLE IF EXISTS llm_summaries")    # simulate a pre-summarize index
    con.commit()
    out = render_keymd(con, path)                        # must not raise
    assert "summary: Doc here." in out
    con.close()
