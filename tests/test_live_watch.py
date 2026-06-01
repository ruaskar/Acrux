"""spawn_watcher — background filesystem refresh for serve/graph."""
import time

import pytest

import keymd.engine.parsers.python  # noqa: F401
from keymd.engine import config, index


def test_spawn_watcher_refreshes_on_new_file(monkeypatch, tmp_path):
    pytest.importorskip("watchdog")  # skip cleanly if extra absent
    proj = tmp_path / "proj"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "a.py").write_text('"""A."""\ndef a(): return 1\n', encoding="utf-8")
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(proj))
    monkeypatch.setenv("KEYMD_INDEX_PATH", str(tmp_path / "index.db"))
    config.project_pkg_prefixes.cache_clear()
    config._git_toplevel.cache_clear()
    index.build(verbose=False)

    from keymd.proxy.live import spawn_watcher
    obs = spawn_watcher(str(proj), delay=0.15)
    assert obs is not None
    try:
        # create a NEW file after the index was built
        (proj / "pkg" / "b.py").write_text('"""B."""\ndef b(): return 2\n', encoding="utf-8")
        from keymd.engine import db
        deadline = time.monotonic() + 8
        found = False
        while time.monotonic() < deadline:
            con = db.connect(config.index_path())
            row = con.execute("SELECT 1 FROM symbols WHERE name='b'").fetchone()
            con.close()
            if row:
                found = True
                break
            time.sleep(0.25)
        assert found, "watcher did not index the new file"
    finally:
        obs.stop()
        obs.join()


def test_spawn_watcher_returns_none_without_watchdog(monkeypatch, tmp_path):
    # Simulate the extra being absent → graceful None, no raise.
    import builtins
    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("watchdog"):
            raise ImportError("no watchdog")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    monkeypatch.setenv("KEYMD_PROJECT_ROOT", str(tmp_path))
    from keymd.proxy import live
    assert live.spawn_watcher(str(tmp_path)) is None
