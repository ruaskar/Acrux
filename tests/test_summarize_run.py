"""Tests for summarize orchestration: gated-scope, incremental, redacted, own-key."""
import pytest

import keymd.engine.parsers.python  # noqa: F401  (registers .py parser)
from keymd.engine import config, db, index
from keymd.summarize import run as srun


def _mk_repo(tmp_path):
    big = "def f():\n" + "    x = 1\n" * 80          # > default threshold 50 loc
    (tmp_path / "big.py").write_text(big, encoding="utf-8")
    (tmp_path / "small.py").write_text("def g():\n    return 1\n", encoding="utf-8")
    return tmp_path


def test_summarize_gated_only_incremental_and_redacted(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path)
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(repo))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(repo / ".keymd" / "index.db"))
    monkeypatch.setenv("KEYMD_OPENAI_BASE", "https://fake.local")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config.project_pkg_prefixes.cache_clear(); config._git_toplevel.cache_clear()
    index.build(verbose=False)

    calls = {"n": 0}

    def fake_call(wire, base, key, headers, body):
        calls["n"] += 1
        # model echoes a secret from the file -> must be redacted before caching
        return {"choices": [{"message": {"content":
            "Summary. token sk-ant-SECRETSECRETSECRET123456 here."}}]}

    monkeypatch.setattr(srun, "_call", fake_call)

    r1 = srun.summarize(str(repo), "openai", "gpt-4o", limit=100, threshold=50)
    assert r1["summarized"] == 1 and calls["n"] == 1     # only big.py gated; small.py excluded

    # cached summary is redacted (read the single row back directly — path-agnostic)
    con = db.connect(config.index_path())
    row = con.execute("SELECT summary FROM llm_summaries").fetchone()
    con.close()
    assert row is not None
    assert "sk-ant-SECRETSECRETSECRET123456" not in row[0]
    assert "<redacted>" in row[0]

    # second run: nothing changed -> incremental skip, no new calls
    r2 = srun.summarize(str(repo), "openai", "gpt-4o", limit=100, threshold=50)
    assert r2["summarized"] == 0 and r2["skipped"] >= 1 and calls["n"] == 1


def test_summarize_missing_key_fails_loudly(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path)
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(repo))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(repo / ".keymd" / "index.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config.project_pkg_prefixes.cache_clear(); config._git_toplevel.cache_clear()
    index.build(verbose=False)
    with pytest.raises(SystemExit):
        srun.summarize(str(repo), "openai", "gpt-4o", limit=100, threshold=50)


def test_summarize_unknown_wire_fails(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path)
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(repo))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(repo / ".keymd" / "index.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    config.project_pkg_prefixes.cache_clear(); config._git_toplevel.cache_clear()
    with pytest.raises(SystemExit):
        srun.summarize(str(repo), "gemini", "x", limit=1, threshold=50)
