"""Tests for the sha-keyed LLM-summary cache (engine.summary_store)."""
from keymd.engine import db, summary_store


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
