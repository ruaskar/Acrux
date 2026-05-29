"""Regressions for the end-to-end adversarial-review findings."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from keymd.engine import config, db, index, query, refresh, sync_one
import keymd.engine.parsers.python  # noqa: F401


def test_query_finds_recased_path(env_proj):
    # Fix 8: a differently-cased path must resolve to the indexed key.
    index.build(verbose=False)
    parser_py = str(Path(env_proj) / "pkg" / "parser.py")
    recased = str(Path(env_proj) / "pkg" / "PARSER.py")
    if config.canonical(recased) != config.canonical(parser_py):
        pytest.skip("case-sensitive filesystem; casing test N/A")
    assert query.symbols(recased)             # non-empty (was [] under abspath)
    assert query.impact(recased)["unique_files"] >= 1


def test_sync_recased_path_no_duplicate_rows(env_proj):
    # Fix 8: sync via a mis-cased path must UPDATE in place, not duplicate.
    index.build(verbose=False)
    parser_py = Path(env_proj) / "pkg" / "parser.py"
    recased = str(parser_py.parent / "PARSER.py")
    if config.canonical(recased) != config.canonical(str(parser_py)):
        pytest.skip("case-sensitive filesystem")
    key = Path(str(parser_py)[:-3] + ".key.md")
    try:
        sync_one.sync_one(recased)
        con = db.connect(config.index_path())
        n = con.execute("SELECT COUNT(*) FROM files WHERE path LIKE ?",
                        ("%arser.py",)).fetchone()[0]
        con.close()
        assert n == 1
    finally:
        key.unlink(missing_ok=True)
        Path(str(key) + ".tmp").unlink(missing_ok=True)


def test_refresh_then_search_without_second_build(env_proj):
    # Fix 5: search works after build -> refresh (refresh now updates FTS).
    index.build(verbose=False)
    parser_py = Path(env_proj) / "pkg" / "parser.py"
    key = Path(str(parser_py)[:-3] + ".key.md")
    key.unlink(missing_ok=True)  # defensive: no stale sidecar from a prior test
    try:
        assert refresh.refresh_one(str(parser_py)) is True
        hits = query.search("parse_header")
        assert any("parser.key.md" in p for p, _ in hits)
    finally:
        key.unlink(missing_ok=True)
        Path(str(key) + ".tmp").unlink(missing_ok=True)


def test_flat_repo_top_level_files_indexed(monkeypatch, tmp_path):
    # Fix 6: files directly under the project root must be indexed.
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / ".keymd" / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    stats = index.build(verbose=False)
    assert stats["files"] >= 1 and stats["symbols"] >= 1


def test_openai_loopguard_marker_harvested():
    # Fix 3: the loop-guard must see OpenAI {role:tool, content:str} markers.
    from keymd.proxy import gate
    marker = "⟪keymd-summary:/abs/big.py⟫\nsummary..."
    oa = [{"role": "tool", "tool_call_id": "t1", "content": marker}]
    assert "/abs/big.py" in gate.summarized_paths(oa)
    # and a re-read of that path classifies as host (not re-gated)
    from keymd.proxy.adapters.base import ToolCall
    d = gate.classify(ToolCall("2", "Read", {"file_path": "/abs/big.py"}),
                      summarized=gate.summarized_paths(oa), threshold=0)
    assert d.kind == "host"


def test_watch_command_dispatches(env_proj, monkeypatch):
    # Fix 1: `keymd watch` is a real, dispatchable subcommand.
    from keymd import cli
    import keymd.watcher.run as run
    called = {}
    monkeypatch.setattr(run, "serve", lambda **k: called.setdefault("ok", k))
    assert cli.main(["watch"]) == 0
    assert "ok" in called


def test_programmatic_build_registers_parser(env_proj):
    # Fix 2: index.build() in a fresh process (no explicit parser import) still
    # parses, because the parsers package registers on import.
    code = ("import json; from keymd.engine import index; "
            "print(json.dumps(index.build(verbose=False)))")
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, env=dict(os.environ))
    assert out.returncode == 0, out.stderr
    import json
    stats = json.loads(out.stdout.strip().splitlines()[-1])
    assert stats["symbols"] > 0     # was 0 when registration only happened in cli.py
