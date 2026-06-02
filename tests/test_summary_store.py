"""Tests for the sha-keyed LLM-summary cache (engine.summary_store) + its
survival across a full `index.build()` rebuild."""
import keymd.engine.parsers.python  # noqa: F401  (registers .py parser for build)
from keymd.engine import config, db, index, summary_store


def test_put_get_roundtrip_sha_keyed(tmp_path):
    p = tmp_path / "index.db"
    con = db.connect(p, create=True)
    summary_store.ensure_table(con)
    summary_store.put(con, "a.py", "sha111", "Does X.", "gpt-4o")
    assert summary_store.get(con, "a.py", "sha111") == "Does X."
    # sha mismatch -> miss (file changed since summary was written)
    assert summary_store.get(con, "a.py", "sha999") is None
    # overwrite on new sha
    summary_store.put(con, "a.py", "sha222", "Does Y now.", "gpt-4o")
    assert summary_store.get(con, "a.py", "sha222") == "Does Y now."
    con.close()


def test_ensure_table_idempotent_on_existing_index(tmp_path):
    # summarize opens an index built WITHOUT create=True -> table may be absent
    p = tmp_path / "index.db"
    db.connect(p, create=True).close()
    con = db.connect(p)                 # no create
    summary_store.ensure_table(con)     # must not raise even if already present
    summary_store.ensure_table(con)
    summary_store.put(con, "b.py", "s", "txt", "m")
    assert summary_store.get(con, "b.py", "s") == "txt"
    con.close()


def test_cache_survives_rebuild_but_drops_stale_and_orphan(tmp_path, monkeypatch):
    """A full `index.build()` unlinks the db; the LLM cache must be preserved for
    files still present at the SAME sha, and dropped for changed (stale-sha) or
    deleted (orphan) files."""
    (tmp_path / "keep.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "change.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / ".keymd" / "index.db"))
    config.project_pkg_prefixes.cache_clear(); config._git_toplevel.cache_clear()
    index.build(verbose=False)

    con = db.connect(config.index_path())
    summary_store.ensure_table(con)
    keep = config.canonical(str(tmp_path / "keep.py"))
    change = config.canonical(str(tmp_path / "change.py"))
    orphan = config.canonical(str(tmp_path / "gone.py"))
    keep_sha = con.execute("SELECT sha256 FROM files WHERE path=?", (keep,)).fetchone()[0]
    change_sha = con.execute("SELECT sha256 FROM files WHERE path=?", (change,)).fetchone()[0]
    summary_store.put(con, keep, keep_sha, "KEEP summary.", "m")
    summary_store.put(con, change, change_sha, "OLD change summary.", "m")
    summary_store.put(con, orphan, "deadsha", "ORPHAN summary.", "m")
    con.close()

    # change.py is edited (new sha); gone.py is deleted
    (tmp_path / "change.py").write_text("def b():\n    return 999\n", encoding="utf-8")
    index.build(verbose=False)                       # the rebuild that used to wipe the cache

    con = db.connect(config.index_path())
    new_change_sha = con.execute("SELECT sha256 FROM files WHERE path=?",
                                 (change,)).fetchone()[0]
    # unchanged file: summary survived the rebuild
    assert summary_store.get(con, keep, keep_sha) == "KEEP summary."
    # changed file: stale-sha row dropped (not served, not lingering at old sha)
    assert summary_store.get(con, change, change_sha) is None
    assert summary_store.get(con, change, new_change_sha) is None
    # deleted file: orphan row dropped
    assert summary_store.get(con, orphan, "deadsha") is None
    rows = con.execute("SELECT COUNT(*) FROM llm_summaries").fetchone()[0]
    assert rows == 1                                  # only KEEP remains
    con.close()


def test_rebuild_over_pre_summarize_index_does_not_crash(tmp_path, monkeypatch):
    """An index built before this feature has no llm_summaries table. The snapshot
    step must still close its handle (finally) so the unlink doesn't fail with a
    locked file on Windows (WinError 32). Regression for the build-preserve fix."""
    (tmp_path / "x.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / ".keymd" / "index.db"))
    config.project_pkg_prefixes.cache_clear(); config._git_toplevel.cache_clear()
    index.build(verbose=False)
    # simulate a pre-summarize index: drop the table the new schema would have made
    con = db.connect(config.index_path())
    con.execute("DROP TABLE IF EXISTS llm_summaries")
    con.commit(); con.close()
    # the rebuild must succeed (not raise PermissionError on the unlink)
    res = index.build(verbose=False)
    assert res["files"] >= 1
